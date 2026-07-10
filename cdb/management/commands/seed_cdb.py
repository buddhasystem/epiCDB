"""
Management command: python manage.py seed_cdb
Populates the CDB with the BEMC / BTOF sample dataset.

Kept in sync with the current cdb/models.py schema -- it only touches
fields and models that actually exist there. In particular:
  * There is no ComponentFunction model and no Component.function field,
    so components are described directly via name/description instead.
  * Django's built-in Group model has no description field, so groups
    are created by name only.
  * ComponentInstance has no qr_id field; instances are identified by
    their human-readable tag (unique per component).

Idempotent: safe to run multiple times, never duplicates or clobbers
existing records (uses get_or_create() throughout; passwords are only
set the first time an account is created).
"""
from django.contrib.auth.models import User, Group
from django.core.management.base import BaseCommand
from cdb.models import (
    Institution, Location, TechnicalSystem, Component, ComponentInstance,
    UserProfile, PropertyType, PropertyValue,
)


class Command(BaseCommand):
    help = "Seed the CDB with the BEMC/BTOF sample dataset"

    def handle(self, *args, **options):
        self.stdout.write("Seeding CDB …")

        # Groups
        grp = {}
        for n in ["BEMC", "BTOF"]:
            g, _ = Group.objects.get_or_create(name=n)
            grp[n] = g

        # Users
        # Note: a freshly created User has password="", and Django's
        # has_usable_password() treats an empty string as "usable" (it only
        # checks for the "!" unusable-password marker) -- so it can't be used
        # here to detect "needs a password set". Use the get_or_create()
        # "created" flag instead, so the password is set once on first seed
        # and never clobbered on subsequent idempotent re-runs.
        def mkuser(username, is_staff=False, is_superuser=False, groups=(),
                   first_name="", last_name="", email=""):
            u, created = User.objects.get_or_create(
                username=username,
                defaults={"is_staff": is_staff, "is_superuser": is_superuser},
            )
            if created:
                u.set_password(username)
            # first/last name and email are safe to keep in sync on every
            # run (unlike the password, they're not secret and there's no
            # harm in re-applying the seed's intended values).
            u.first_name = first_name
            u.last_name  = last_name
            u.email      = email
            u.save()
            if groups:
                u.groups.set([grp[g] for g in groups])
            return u

        mkuser("admin", is_staff=True, is_superuser=True)
        mkuser("maxim", is_staff=True, is_superuser=True,
               first_name="Maxim", email="buddhasystem@gmail.com")
        gnigmat = mkuser("gnigmat", groups=["BTOF"],
                          first_name="Grigory", last_name="Nigmatkulov",
                          email="gnigmat@uic.edu")
        crafts  = mkuser("crafts",  groups=["BEMC"],
                          first_name="Casey", last_name="Crafts",
                          email="crafts@cua.edu")

        # Technical systems, each owned by a responsible group
        ts = {}
        for n, group_name in [
            ("BEMC-CRYSTAL", "BEMC"),
            ("BEMC-PM",      "BEMC"),
            ("BTOF-Sensor",  "BTOF"),
            ("BTOF-Readout", "BTOF"),
        ]:
            o, _ = TechnicalSystem.objects.get_or_create(
                name=n, defaults={"group": grp[group_name]}
            )
            ts[n] = o

        # Institutions + locations
        cua, _ = Institution.objects.get_or_create(
            name="Catholic University of America",
            defaults={"abbreviation": "CUA", "country": "USA", "city": "Washington, DC",
                      "url": "https://www.cua.edu"},
        )
        uic, _ = Institution.objects.get_or_create(
            name="University of Illinois Chicago",
            defaults={"abbreviation": "UIC", "country": "USA", "city": "Chicago",
                      "url": "https://www.uic.edu"},
        )

        storage_room, _ = Location.objects.get_or_create(
            name="Storage Room", location_type="room", institution=cua,
        )
        test_lab, _ = Location.objects.get_or_create(
            name="Test Lab", location_type="room", institution=uic,
        )

        # Link each user to their home institution.
        for user, inst in [(crafts, cua), (gnigmat, uic)]:
            UserProfile.objects.get_or_create(user=user, defaults={"institution": inst})

        # Components  (Component has no "function" field -- the functional
        # role is folded into the description instead)
        def mkcomp(name, model, desc, sys_name, group_name, owner):
            c, _ = Component.objects.get_or_create(name=name, project="ePIC", defaults=dict(
                model_number=model, description=desc,
                technical_system=ts.get(sys_name),
                owner_group=grp[group_name], owner_user=owner, created_by=owner))
            return c

        crystal = mkcomp(
            "PbWO4 Crystal", "PWO-BEMC-01",
            "Lead tungstate scintillating crystal for the Backward EMCal.",
            "BEMC-CRYSTAL", "BEMC", crafts,
        )
        pm = mkcomp(
            "Hamamatsu S14160-3010PS", "S14160-3010PS",
            "3x3mm 10um-pitch SiPM photosensor for BEMC readout.",
            "BEMC-PM", "BEMC", crafts,
        )
        sensor = mkcomp(
            "AC-LGAD Sensor", "AC-LGAD-v1",
            "AC-coupled Low Gain Avalanche Diode sensor for BTOF.",
            "BTOF-Sensor", "BTOF", gnigmat,
        )
        readout = mkcomp(
            "FCFDv2 Readout", "FCFDv2",
            "Fast Constant-Fraction Discriminator readout ASIC for BTOF.",
            "BTOF-Readout", "BTOF", gnigmat,
        )

        # Component instances -- 2 to 5 per component, spread across the
        # two locations. Identified by tag (unique per component), not by
        # any qr_id field.
        def mkinst(tag, comp, loc, owner, group_name, serial=""):
            i, _ = ComponentInstance.objects.get_or_create(tag=tag, component=comp, defaults=dict(
                location=loc, serial_number=serial,
                owner_group=grp[group_name], owner_user=owner, created_by=owner))
            return i

        crystal_instances = []
        for i in range(1, 4):  # 3 instances
            loc = storage_room if i % 2 else test_lab
            crystal_instances.append(
                mkinst(f"BEMC-CRYSTAL-{i:03d}", crystal, loc, crafts, "BEMC", f"PWO-{i:04d}")
            )

        for i in range(1, 5):  # 4 instances
            loc = storage_room if i % 2 else test_lab
            mkinst(f"BEMC-PM-{i:03d}", pm, loc, crafts, "BEMC", f"HAM-{i:04d}")

        for i in range(1, 3):  # 2 instances
            loc = test_lab if i % 2 else storage_room
            mkinst(f"BTOF-SENSOR-{i:03d}", sensor, loc, gnigmat, "BTOF", f"LGAD-{i:04d}")

        for i in range(1, 6):  # 5 instances
            loc = test_lab if i % 2 else storage_room
            mkinst(f"BTOF-READOUT-{i:03d}", readout, loc, gnigmat, "BTOF", f"FCFD-{i:04d}")

        # Property types + a couple of example values, to demonstrate
        # component -> instance property inheritance (and overriding).
        weight_pt, _ = PropertyType.objects.get_or_create(
            name="Weight", defaults={"category": "physical", "default_units": "kg"},
        )
        datasheet_pt, _ = PropertyType.objects.get_or_create(
            name="Datasheet", defaults={"category": "documentation", "handler": "document"},
        )
        timing_constant_pt, _ = PropertyType.objects.get_or_create(
            name="Timing Constant", defaults={"category": "physical", "default_units": "ps"},
        )
        length_pt, _ = PropertyType.objects.get_or_create(
            name="Length", defaults={"category": "physical", "default_units": "cm"},
        )
        width_pt, _ = PropertyType.objects.get_or_create(
            name="Width", defaults={"category": "physical", "default_units": "cm"},
        )
        height_pt, _ = PropertyType.objects.get_or_create(
            name="Height", defaults={"category": "physical", "default_units": "cm"},
        )

        # Component-level defaults: every instance of the crystal inherits
        # these unless it overrides the same (property_type, tag) pair.
        PropertyValue.objects.get_or_create(
            component=crystal, property_type=weight_pt, tag="",
            defaults={"value": "0.45", "units": "kg"},
        )
        PropertyValue.objects.get_or_create(
            component=crystal, property_type=datasheet_pt, tag="",
            defaults={"value": "https://example.org/pwo-crystal-datasheet.pdf"},
        )
        PropertyValue.objects.get_or_create(
            component=crystal, property_type=length_pt, tag="",
            defaults={"value": "20", "units": "cm"},
        )
        PropertyValue.objects.get_or_create(
            component=crystal, property_type=width_pt, tag="",
            defaults={"value": "2", "units": "cm"},
        )
        PropertyValue.objects.get_or_create(
            component=crystal, property_type=height_pt, tag="",
            defaults={"value": "2", "units": "cm"},
        )

        # One instance overrides the inherited Weight -- this particular
        # crystal was measured slightly lighter than the catalog default.
        if crystal_instances:
            PropertyValue.objects.get_or_create(
                component_instance=crystal_instances[0], property_type=weight_pt, tag="",
                defaults={"value": "0.44", "units": "kg"},
            )

        self.stdout.write(self.style.SUCCESS(
            f"\nDone.  admin/admin, maxim/maxim | "
            f"Groups:{Group.objects.filter(name__in=['BEMC','BTOF']).count()}  "
            f"Systems:{TechnicalSystem.objects.count()}  "
            f"Components:{Component.objects.count()}  "
            f"Instances:{ComponentInstance.objects.count()}  "
            f"Institutions:{Institution.objects.count()}"
        ))

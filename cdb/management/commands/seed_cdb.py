"""
Management command: python manage.py seed_cdb
Populates the CDB with realistic ePIC/BNL sample data.

Kept in sync with the current cdb/models.py schema -- it only touches
fields and models that actually exist there. In particular:
  * There is no ComponentFunction model and no Component.function field,
    so components are described directly via name/description instead.
  * Django's built-in Group model has no description field, so groups
    are created by name only.
  * ComponentInstance has no qr_id field; instances are identified by
    their human-readable tag (unique per component).
"""
from django.contrib.auth.models import User, Group
from django.core.management.base import BaseCommand
from cdb.models import (
    Institution, Location, PropertyType,
    TechnicalSystem, Source,
    Component, ComponentSource, ComponentInstance,
    Design, DesignElement, PropertyValue, LogEntry,
)


class Command(BaseCommand):
    help = "Seed the CDB with sample data"

    def handle(self, *args, **options):
        self.stdout.write("Seeding CDB …")

        # Users
        # Note: a freshly created User has password="", and Django's
        # has_usable_password() treats an empty string as "usable" (it only
        # checks for the "!" unusable-password marker) -- so it can't be used
        # here to detect "needs a password set". Use the get_or_create()
        # "created" flag instead, so the password is set once on first seed
        # and never clobbered on subsequent idempotent re-runs.
        admin, created = User.objects.get_or_create(username="admin", defaults={"is_staff": True, "is_superuser": True})
        if created:
            admin.set_password("admin"); admin.save()
        srahman, _ = User.objects.get_or_create(username="srahman")
        cpeng,   _ = User.objects.get_or_create(username="cpeng")

        # Groups (Django's built-in Group model only has a "name" field)
        grp = {}
        for n in ["DIAG", "CTL", "MED", "APSU_VAC", "EPIC_TRK", "EPIC_CAL"]:
            g, _ = Group.objects.get_or_create(name=n); grp[n] = g

        # Institutions
        inst = {}
        for name, abbr, country, city, url in [
            ("Brookhaven National Laboratory",   "BNL",      "USA",         "Upton",      "https://www.bnl.gov"),
            ("European Organization for Nuclear Research", "CERN", "Switzerland", "Geneva", "https://www.cern.ch"),
            ("Fermi National Accelerator Laboratory", "FNAL", "USA",         "Batavia",    "https://www.fnal.gov"),
            ("Argonne National Laboratory",      "ANL",      "USA",         "Lemont",     "https://www.anl.gov"),
        ]:
            obj, _ = Institution.objects.get_or_create(name=name, defaults={"abbreviation": abbr, "country": country, "city": city, "url": url})
            inst[abbr] = obj

        # Locations  (all need an institution)
        def mkloc(name, ltype, institution_abbr, parent=None):
            obj, _ = Location.objects.get_or_create(
                name=name,
                location_type=ltype,
                institution=inst[institution_abbr],
                defaults={"parent": parent}
            )
            return obj

        bldg510   = mkloc("Building 510",          "building", "BNL")
        room382   = mkloc("Room 382",              "room",     "BNL", bldg510)
        fwd_hall  = mkloc("Forward Detector Hall", "building", "BNL")
        rack_a1   = mkloc("Rack A1",              "cabinet",  "BNL", fwd_hall)
        cern_b40  = mkloc("Building 40",          "building", "CERN")
        cern_lab  = mkloc("Clean Room 40-1-B04",  "room",     "CERN", cern_b40)
        fnal_mp9  = mkloc("MP9",                  "building", "FNAL")
        fnal_room = mkloc("Assembly Bay",         "room",     "FNAL", fnal_mp9)

        # Technical systems
        ts = {}
        for n in ["Tracking", "Calorimetry", "Vacuum", "Controls", "Diagnostics"]:
            o, _ = TechnicalSystem.objects.get_or_create(name=n); ts[n] = o

        # Sources
        src = {}
        for n, e, u in [
            ("Hamamatsu Photonics","sales@hamamatsu.com","https://www.hamamatsu.com"),
            ("CAEN S.p.A.","info@caen.it","https://www.caen.it"),
            ("Concurrent Technologies","sales@ct.com","https://www.ct.com"),
            ("Fermilab In-house","prodsvc@fnal.gov",""),
            ("Vacuum One","vac@vacuumone.com",""),
        ]:
            o, _ = Source.objects.get_or_create(name=n, defaults={"contact_email": e, "url": u}); src[n] = o

        # Property types
        pt = {}
        for n, cat, handler in [
            ("PDMLink Drawing","documentation","pdmlink"),
            ("Document/Drawing","documentation","document"),
            ("QA Inspection Report","qa","document"),
            ("QA Level","qa",""),
            ("Form Factor","physical",""),
            ("Strip Pitch","physical",""),
            ("Active Area","physical",""),
            ("Max Current","physical",""),
            ("Slot Length","physical",""),
            ("Purchase Requisition","documentation","http_link"),
            ("Date In Service","maintenance","date"),
            ("Image","documentation","image"),
            ("HTTP Link","documentation","http_link"),
        ]:
            o, _ = PropertyType.objects.get_or_create(name=n, defaults={"category": cat, "handler": handler}); pt[n] = o

        # Catalog  (Component has no "function" field -- the functional
        # role is folded into the description instead)
        def mkcomp(name, model, desc, sys, grp_name):
            c, _ = Component.objects.get_or_create(name=name, project="ePIC", defaults=dict(
                model_number=model, description=desc,
                technical_system=ts.get(sys),
                owner_group=grp[grp_name], owner_user=admin, created_by=admin))
            return c

        svt  = mkcomp("ePIC SVT Silicon Strip Sensor","HPK-SVT-01","Silicon Strip Sensor. Single-sided AC-coupled strip sensor, pitch 25µm.","Tracking","EPIC_TRK")
        maps = mkcomp("ePIC ITS3 MAPS Pixel Sensor","ALICE-ITS3-v1","MAPS Pixel Sensor. 10µm pixel pitch.","Tracking","EPIC_TRK")
        asic = mkcomp("EICREADER ASIC","EICRD-23","ASIC Readout Chip. 128-ch 130nm CMOS readout ASIC.","Tracking","EPIC_TRK")
        xtal = mkcomp("PbWO4 EMCal Crystal","CMS-ECAL-W2","EMCal Crystal. 23×23×230mm lead tungstate crystal.","Calorimetry","EPIC_CAL")
        sipm = mkcomp("SiPM S13360-6050PE","S13360-6050PE","SiPM Photodetector. 6×6mm Hamamatsu SiPM, 50µm pitch.","Calorimetry","EPIC_CAL")
        hvm  = mkcomp("CAEN A1511B HV Module","A1511B","Power Supply. 16-ch 500V HV module.","Controls","CTL")
        cpu  = mkcomp("AM31x MicroTCA CPU","AM310/02-52","CPU. 2nd Gen Intel Core AMC CPU.","Controls","CTL")

        for comp, s, pn, cost, role in [
            (svt,  "Hamamatsu Photonics","HPK-SVT-01",320,"manufacturer"),
            (maps, "Fermilab In-house","ITS3-001",0,"manufacturer"),
            (asic, "Fermilab In-house","EICRD-23",85,"both"),
            (xtal, "Fermilab In-house","CMS-W2",10,"vendor"),
            (sipm, "Hamamatsu Photonics","S13360-6050PE",42,"vendor"),
            (hvm,  "CAEN S.p.A.","A1511B",1200,"vendor"),
            (cpu,  "Concurrent Technologies","AM310/02-52",2209,"vendor"),
        ]:
            ComponentSource.objects.get_or_create(component=comp, source=src[s], defaults={"part_number": pn, "cost": cost, "role": role})

        def add_prop(**kw):
            ptype_name = kw.pop("ptype")
            ptype = pt.get(ptype_name)
            if not ptype: return
            PropertyValue.objects.get_or_create(property_type=ptype, **kw)

        add_prop(component=svt,  ptype="Strip Pitch",  tag="", value="25",    units="µm")
        add_prop(component=svt,  ptype="Active Area",  tag="", value="98×98", units="mm²")
        add_prop(component=sipm, ptype="Active Area",  tag="", value="6×6",   units="mm²")
        add_prop(component=cpu,  ptype="Form Factor",  tag="", value="MicroTCA")

        # Instances -- spread across BNL, CERN, FNAL. Identified by tag
        # (unique per component), not by any qr_id field.
        def mkinst(tag, comp, loc, serial="", grp_name="EPIC_TRK"):
            i, _ = ComponentInstance.objects.get_or_create(tag=tag, component=comp, defaults=dict(
                location=loc, serial_number=serial,
                owner_group=grp[grp_name], owner_user=admin, created_by=admin))
            return i

        i_svt1 = mkinst("SVT-Sensor-001", svt,  room382,   "HPK-22-001")
        i_svt2 = mkinst("SVT-Sensor-002", svt,  room382,   "HPK-22-002")
        i_svt3 = mkinst("SVT-Sensor-003", svt,  cern_lab,  "HPK-22-003")   # at CERN
        i_svt4 = mkinst("SVT-Sensor-004", svt,  fnal_room, "HPK-22-004")   # at FNAL
        i_spm1 = mkinst("SiPM-001",       sipm, room382,   "HAM-23-001","EPIC_CAL")
        i_spm2 = mkinst("SiPM-002",       sipm, cern_lab,  "HAM-23-002","EPIC_CAL")
        i_cpu1 = mkinst("CPU-001",        cpu,  rack_a1,   "AMC-2013-001","CTL")
        i_hv1  = mkinst("HV-Mod-001",     hvm,  rack_a1,   "CAEN-22-001", "CTL")

        add_prop(component_instance=i_svt1, ptype="QA Level", tag="", value="A")
        add_prop(component_instance=i_svt3, ptype="QA Level", tag="", value="B")

        def addlog(msg, topic="", comp=None, inst=None, des=None, user=admin):
            kw = {"topic": topic}
            if comp: kw["component"] = comp
            if inst: kw["component_instance"] = inst
            if des:  kw["design"] = des
            LogEntry.objects.get_or_create(entry=msg, **kw, defaults={"logged_by": user})

        addlog("Incoming QA passed, no visible damage.", "inspection", inst=i_svt1, user=srahman)
        addlog("Shipped to CERN for beam test.", "other", inst=i_svt3, user=srahman)
        addlog("Shipped to FNAL for cosmic stand.", "other", inst=i_svt4, user=srahman)
        addlog("CPU installed in Rack A1, bias ramp OK.", "installation", inst=i_cpu1, user=cpeng)
        addlog("First batch of 200 sensors received from Hamamatsu.", "other", comp=svt, user=srahman)

        # Designs
        def mkdes(name, desc, grp_name):
            d, _ = Design.objects.get_or_create(name=name, defaults=dict(
                description=desc, project="ePIC",
                owner_group=grp[grp_name], owner_user=admin, created_by=admin))
            return d

        svt_mod  = mkdes("ePIC SVT Layer 1 Module","4 strip sensors + 4 ASICs on carbon-fibre stave.","EPIC_TRK")
        emcal    = mkdes("ePIC EMCal Cell","1 PbWO4 crystal + 1 SiPM + HV routing.","EPIC_CAL")
        daq      = mkdes("ePIC DAQ MicroTCA Crate","MicroTCA crate: CPU + HV module.","CTL")
        full_trk = mkdes("ePIC Tracking System","Full central tracking: SVT barrel + forward discs.","EPIC_TRK")

        def mkel(design, name, comp=None, child=None, inst=None, qty=1, desc=""):
            DesignElement.objects.get_or_create(design=design, element_name=name,
                defaults=dict(component=comp, child_design=child, installed_instance=inst, quantity=qty, description=desc))

        mkel(svt_mod, "SVT-L1-SEN-A", comp=svt,  inst=i_svt1)
        mkel(svt_mod, "SVT-L1-SEN-B", comp=svt,  inst=i_svt2)
        mkel(svt_mod, "SVT-L1-SEN-C", comp=svt)
        mkel(svt_mod, "SVT-L1-SEN-D", comp=svt)
        mkel(svt_mod, "SVT-L1-ASIC-A", comp=asic)
        mkel(svt_mod, "SVT-L1-ASIC-B", comp=asic)

        mkel(emcal, "EMC-XTAL-01", comp=xtal)
        mkel(emcal, "EMC-SIPM-01", comp=sipm, inst=i_spm1)

        mkel(daq, "DAQ-CPU-01", comp=cpu, inst=i_cpu1)
        mkel(daq, "DAQ-HV-01",  comp=hvm, inst=i_hv1)

        mkel(full_trk, "TRK-SVT-L1-MOD-01", child=svt_mod, desc="phi=0")
        mkel(full_trk, "TRK-SVT-L1-MOD-02", child=svt_mod, desc="phi=30°")
        mkel(full_trk, "TRK-DAQ-CRATE-01",  child=daq)

        add_prop(design=svt_mod, ptype="Document/Drawing", tag="Assembly Drawing", value="EPIC-SVT-L1-ASSY-v1.pdf")
        addlog("Design review approved for prototyping.", "other", des=svt_mod, user=srahman)
        addlog("First crate powered on in B510/382.", "installation", des=daq, user=cpeng)

        self.stdout.write(self.style.SUCCESS(
            f"\nDone.  admin/admin | "
            f"Components:{Component.objects.count()}  "
            f"Instances:{ComponentInstance.objects.count()}  "
            f"Designs:{Design.objects.count()}  "
            f"Institutions:{Institution.objects.count()}"
        ))
    
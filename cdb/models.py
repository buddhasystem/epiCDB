"""
Component Database (CDB) models.
Three primary domains: Component Catalog, Component Inventory, Design.
Supporting: Institution, Location, Ownership, Properties, Logs.
Groups use Django's built-in auth.Group.
"""

import uuid
from django.db import models
from django.contrib.auth.models import User, Group
from django.utils import timezone


# ---------------------------------------------------------------------------
# Supporting tables
# ---------------------------------------------------------------------------

class Institution(models.Model):
    """
    Top-level site anchor (BNL, CERN, Fermilab, …).
    Locations belong to an institution, enabling multi-site inventory tracking.
    """
    id = models.CharField(max_length=36, primary_key=True, editable=False)
    name         = models.CharField(max_length=128, unique=True)
    abbreviation = models.CharField(max_length=16,  blank=True)
    country      = models.CharField(max_length=64,  blank=True)
    city         = models.CharField(max_length=64,  blank=True)
    url          = models.URLField(blank=True)
    description  = models.TextField(blank=True)

    def save(self, *args, **kwargs):
        if not self.id:
            self.id = str(uuid.uuid4())
        super().save(*args, **kwargs)

    def __str__(self):
        return self.abbreviation if self.abbreviation else self.name

    class Meta:
        ordering = ["name"]


class Location(models.Model):
    """
    Physical location hierarchy within an institution:
    building → room → cabinet → shelf.
    Every location is anchored to exactly one Institution.
    """
    id = models.CharField(max_length=36, primary_key=True, editable=False)
    LOCATION_TYPES = [
        ("building", "Building"),
        ("room",     "Room"),
        ("cabinet",  "Cabinet"),
        ("shelf",    "Shelf"),
        ("other",    "Other"),
    ]
    name          = models.CharField(max_length=128)
    location_type = models.CharField(max_length=16, choices=LOCATION_TYPES, default="room")
    institution   = models.ForeignKey(
        Institution, null=True, blank=True, on_delete=models.SET_NULL, related_name="locations"
    )
    parent = models.ForeignKey(
        "self", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="children"
    )
    description = models.TextField(blank=True)

    def save(self, *args, **kwargs):
        if not self.id:
            self.id = str(uuid.uuid4())
        super().save(*args, **kwargs)

    def full_path(self):
        """Return slash-separated path: Institution / Building / Room / …"""
        parts = []
        node = self
        while node is not None:
            parts.append(node.name)
            node = node.parent
        parts.append(str(self.institution))
        return " / ".join(reversed(parts))

    def __str__(self):
        return self.full_path()

    class Meta:
        ordering = ["name"]


class PropertyType(models.Model):
    """Predefined property types (extensible by admins)."""
    id = models.CharField(max_length=36, primary_key=True, editable=False)
    HANDLER_CHOICES = [
        ("",                  "None"),
        ("document",          "Document"),
        ("image",             "Image"),
        ("http_link",         "HTTP Link"),
        # ("traveler_template", "Traveler Template"),
        # ("traveler_instance", "Traveler Instance"),

        # ("currency",          "Currency"),
        # ("boolean",           "Boolean"),
        #("date",              "Date"),
    ]
    CATEGORY_CHOICES = [
        ("physical",        "Physical"),
        ("documentation",   "Documentation"),
        # ("qa",            "QA"),
        # ("maintenance",    "Maintenance"),
        # ("design",         "Design"),
        # ("status",         "Status"),
        # ("other",          "Other"),
        # ("lattice",        "Lattice"),
        #("safety",         "Safety"),
    ]
    name          = models.CharField(max_length=128, unique=True)
    category      = models.CharField(max_length=32, choices=CATEGORY_CHOICES, default="other")
    handler       = models.CharField(max_length=32, choices=HANDLER_CHOICES, blank=True, default="")
    description   = models.TextField(blank=True)
    default_units = models.CharField(max_length=64, blank=True)
    default_value = models.CharField(max_length=256, blank=True)

    def save(self, *args, **kwargs):
        if not self.id:
            self.id = str(uuid.uuid4())
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ["name"]


# ---------------------------------------------------------------------------
# Abstract base: ownership + timestamps
# ---------------------------------------------------------------------------

class OwnedModel(models.Model):
    owner_user      = models.ForeignKey(User,  null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    owner_group     = models.ForeignKey(Group, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    group_writeable = models.BooleanField(default=False)
    created_by      = models.ForeignKey(User,  null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_on      = models.DateTimeField(default=timezone.now, editable=False)
    modified_by     = models.ForeignKey(User,  null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    modified_on     = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


# ---------------------------------------------------------------------------
# Cross-domain: PropertyValue and LogEntry
# ---------------------------------------------------------------------------

class PropertyValue(models.Model):
    id = models.CharField(max_length=36, primary_key=True, editable=False)
    property_type = models.ForeignKey(PropertyType, on_delete=models.CASCADE)
    tag           = models.CharField(max_length=128, blank=True)
    value         = models.TextField(blank=True)
    units         = models.CharField(max_length=64,  blank=True)
    description   = models.TextField(blank=True)
    is_dynamic    = models.BooleanField(default=False)
    user_writable = models.BooleanField(default=True)

    # One of these FKs is set; the rest are NULL
    component          = models.ForeignKey("Component",         null=True, blank=True, on_delete=models.CASCADE, related_name="properties")
    component_instance = models.ForeignKey("ComponentInstance", null=True, blank=True, on_delete=models.CASCADE, related_name="properties")
    design             = models.ForeignKey("Design",            null=True, blank=True, on_delete=models.CASCADE, related_name="properties")
    design_element     = models.ForeignKey("DesignElement",     null=True, blank=True, on_delete=models.CASCADE, related_name="properties")

    created_on  = models.DateTimeField(default=timezone.now, editable=False)
    modified_on = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.id:
            self.id = str(uuid.uuid4())
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.property_type.name}: {self.value[:40]}"

    class Meta:
        ordering = ["property_type__name"]


class LogEntry(models.Model):
    id = models.CharField(max_length=36, primary_key=True, editable=False)
    TOPIC_CHOICES = [
        ("",             "General"),
        ("installation", "Installation"),
        ("maintenance",  "Maintenance"),
        ("inspection",   "Inspection"),
        ("repair",       "Repair"),
        ("decommission", "Decommission"),
        ("other",        "Other"),
    ]
    topic      = models.CharField(max_length=32, choices=TOPIC_CHOICES, blank=True, default="")
    entry      = models.TextField()
    attachment = models.FileField(upload_to="log_attachments/", null=True, blank=True)
    logged_by  = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="cdb_log_entries")
    timestamp  = models.DateTimeField(default=timezone.now)

    component          = models.ForeignKey("Component",         null=True, blank=True, on_delete=models.CASCADE, related_name="log_entries")
    component_instance = models.ForeignKey("ComponentInstance", null=True, blank=True, on_delete=models.CASCADE, related_name="log_entries")
    design             = models.ForeignKey("Design",            null=True, blank=True, on_delete=models.CASCADE, related_name="log_entries")

    def save(self, *args, **kwargs):
        if not self.id:
            self.id = str(uuid.uuid4())
        super().save(*args, **kwargs)

    def __str__(self):
        return f"[{self.timestamp:%Y-%m-%d}] {self.entry[:60]}"

    class Meta:
        ordering = ["-timestamp"]


# ---------------------------------------------------------------------------
# Domain 1 — Component Catalog
# ---------------------------------------------------------------------------

class TechnicalSystem(models.Model):
    id = models.CharField(max_length=36, primary_key=True, editable=False)
    name        = models.CharField(max_length=64, unique=True)
    description = models.TextField(blank=True)
    group       = models.ForeignKey(
        Group, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="technical_systems",
        help_text="Django auth Group responsible for this technical system.",
    )

    def save(self, *args, **kwargs):
        if not self.id:
            self.id = str(uuid.uuid4())
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ["name"]


class Source(models.Model):
    id = models.CharField(max_length=36, primary_key=True, editable=False)
    name          = models.CharField(max_length=256, unique=True)
    contact_email = models.EmailField(blank=True)
    url           = models.URLField(blank=True)
    address       = models.TextField(blank=True)

    def save(self, *args, **kwargs):
        if not self.id:
            self.id = str(uuid.uuid4())
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ["name"]


class Component(OwnedModel):
    id               = models.CharField(max_length=36, primary_key=True, editable=False)
    name             = models.CharField(max_length=256)
    alternate_name   = models.CharField(max_length=256, blank=True)
    model_number     = models.CharField(max_length=128, blank=True)
    description      = models.TextField(blank=True)
    project          = models.CharField(max_length=64,  blank=True, default="ePIC")
    technical_system = models.ForeignKey(TechnicalSystem, null=True, blank=True, on_delete=models.SET_NULL, related_name="components")
    sources          = models.ManyToManyField(Source, through="ComponentSource", blank=True)

    def save(self, *args, **kwargs):
        if not self.id:
            self.id = str(uuid.uuid4())
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ["name"]
        unique_together = [("name", "project")]


class ComponentSource(models.Model):
    id = models.CharField(max_length=36, primary_key=True, editable=False)
    ROLE_CHOICES = [
        ("vendor",       "Vendor"),
        ("manufacturer", "Manufacturer"),
        ("both",         "Vendor & Manufacturer"),
    ]
    component   = models.ForeignKey(Component, on_delete=models.CASCADE)
    source      = models.ForeignKey(Source,    on_delete=models.CASCADE)
    part_number = models.CharField(max_length=128, blank=True)
    cost        = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    role        = models.CharField(max_length=16, choices=ROLE_CHOICES, default="vendor")
    description = models.TextField(blank=True)

    def save(self, *args, **kwargs):
        if not self.id:
            self.id = str(uuid.uuid4())
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.source.name} → {self.component.name}"

    class Meta:
        unique_together = [("component", "source")]


# ---------------------------------------------------------------------------
# Domain 2 — Component Inventory
# ---------------------------------------------------------------------------

class ComponentInstance(OwnedModel):
    id = models.CharField(max_length=36, primary_key=True, editable=False)
    tag              = models.CharField(max_length=128, blank=True)
    serial_number    = models.CharField(max_length=128, blank=True)
    component        = models.ForeignKey(Component,       on_delete=models.PROTECT,  related_name="instances")
    technical_system = models.ForeignKey(TechnicalSystem, null=True, blank=True, on_delete=models.SET_NULL, related_name="component_instances")
    location         = models.ForeignKey(Location,        null=True, blank=True, on_delete=models.SET_NULL, related_name="instances")
    description      = models.TextField(blank=True)

    def save(self, *args, **kwargs):
        """Inherit technical_system from component if not explicitly set."""
        if not self.id:
            self.id = str(uuid.uuid4())
        if self.technical_system_id is None and self.component_id:
            self.technical_system = self.component.technical_system
        super().save(*args, **kwargs)

    def __str__(self):
        label = self.tag or str(self.pk)[:8]
        return f"{label} ({self.component.name})"

    class Meta:
        ordering = ["component", "-created_on"]


# ---------------------------------------------------------------------------
# Domain 3 — Designs
# ---------------------------------------------------------------------------

class Design(OwnedModel):
    id = models.CharField(max_length=36, primary_key=True, editable=False)
    name        = models.CharField(max_length=256, unique=True)
    description = models.TextField(blank=True)
    project     = models.CharField(max_length=64, blank=True, default="ePIC")

    def save(self, *args, **kwargs):
        if not self.id:
            self.id = str(uuid.uuid4())
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ["name"]


class DesignElement(models.Model):
    id = models.CharField(max_length=36, primary_key=True, editable=False)
    design             = models.ForeignKey(Design,             on_delete=models.CASCADE,  related_name="elements")
    element_name       = models.CharField(max_length=128)
    component          = models.ForeignKey(Component,         null=True, blank=True, on_delete=models.SET_NULL, related_name="design_memberships")
    child_design       = models.ForeignKey(Design,            null=True, blank=True, on_delete=models.SET_NULL, related_name="parent_elements")
    installed_instance = models.ForeignKey(ComponentInstance, null=True, blank=True, on_delete=models.SET_NULL, related_name="installed_at")
    quantity           = models.PositiveIntegerField(default=1)
    description        = models.TextField(blank=True)

    def save(self, *args, **kwargs):
        if not self.id:
            self.id = str(uuid.uuid4())
        super().save(*args, **kwargs)

    def element_type(self):
        return "DESIGN" if self.child_design_id else "COMPONENT"

    def __str__(self):
        return f"{self.design.name} / {self.element_name}"

    class Meta:
        ordering = ["element_name"]
        unique_together = [("design", "element_name")]

# ---------------------------------------------------------------------------
# User profile extension
# ---------------------------------------------------------------------------

class UserProfile(models.Model):
    """Extends Django's built-in User with CDB-specific attributes."""
    id          = models.CharField(max_length=36, primary_key=True, editable=False)
    user        = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    institution = models.ForeignKey(Institution, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name='users')

    def save(self, *args, **kwargs):
        if not self.id:
            self.id = str(uuid.uuid4())
        super().save(*args, **kwargs)

    def __str__(self):
        inst = str(self.institution) if self.institution else '—'
        return f"{self.user.username} @ {inst}"

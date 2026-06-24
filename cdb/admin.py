from django.contrib import admin
from .models import (
    Group, Institution, Location, PropertyType, PropertyValue, LogEntry,
    TechnicalSystem, ComponentFunction, Source,
    Component, ComponentSource,
    ComponentInstance,
    Design, DesignElement,
)

# ── Inlines ──────────────────────────────────────────────────────────────────

class PropertyValueComponentInline(admin.TabularInline):
    model = PropertyValue; fk_name = "component"; extra = 0
    fields = ("property_type", "tag", "value", "units", "is_dynamic")

class PropertyValueInstanceInline(admin.TabularInline):
    model = PropertyValue; fk_name = "component_instance"; extra = 0
    fields = ("property_type", "tag", "value", "units", "is_dynamic")

class PropertyValueDesignInline(admin.TabularInline):
    model = PropertyValue; fk_name = "design"; extra = 0
    fields = ("property_type", "tag", "value", "units", "is_dynamic")

class PropertyValueElementInline(admin.TabularInline):
    model = PropertyValue; fk_name = "design_element"; extra = 0
    fields = ("property_type", "tag", "value", "units", "is_dynamic")

class LogComponentInline(admin.TabularInline):
    model = LogEntry; fk_name = "component"; extra = 0
    fields = ("timestamp", "logged_by", "topic", "entry"); readonly_fields = ("timestamp",)

class LogInstanceInline(admin.TabularInline):
    model = LogEntry; fk_name = "component_instance"; extra = 0
    fields = ("timestamp", "logged_by", "topic", "entry"); readonly_fields = ("timestamp",)

class LogDesignInline(admin.TabularInline):
    model = LogEntry; fk_name = "design"; extra = 0
    fields = ("timestamp", "logged_by", "topic", "entry"); readonly_fields = ("timestamp",)

class ComponentSourceInline(admin.TabularInline):
    model = ComponentSource; extra = 0
    fields = ("source", "part_number", "cost", "role")

class ComponentInstanceInline(admin.TabularInline):
    model = ComponentInstance; extra = 0
    fields = ("qr_id", "tag", "serial_number", "location", "owner_group")
    show_change_link = True

class LocationInline(admin.TabularInline):
    model = Location; extra = 0
    fields = ("name", "location_type", "parent", "description")
    show_change_link = True

class DesignElementInline(admin.TabularInline):
    model = DesignElement; fk_name = "design"; extra = 0
    fields = ("element_name", "component", "child_design", "installed_instance", "quantity")
    show_change_link = True

# ── Supporting ────────────────────────────────────────────────────────────────

@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ("name", "description")
    search_fields = ("name",)

@admin.register(Institution)
class InstitutionAdmin(admin.ModelAdmin):
    list_display = ("name", "abbreviation", "city", "country", "url")
    search_fields = ("name", "abbreviation", "city", "country")
    inlines = [LocationInline]

@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ("name", "location_type", "institution", "parent")
    list_filter  = ("location_type", "institution")
    search_fields = ("name",)

@admin.register(PropertyType)
class PropertyTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "handler", "default_units")
    list_filter  = ("category", "handler")
    search_fields = ("name",)

@admin.register(TechnicalSystem)
class TechnicalSystemAdmin(admin.ModelAdmin):
    list_display = ("name", "description")

@admin.register(ComponentFunction)
class ComponentFunctionAdmin(admin.ModelAdmin):
    list_display = ("name", "technical_system")
    list_filter  = ("technical_system",)

@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
    list_display = ("name", "contact_email", "url")
    search_fields = ("name",)

# ── Domain 1: Catalog ─────────────────────────────────────────────────────────

@admin.register(Component)
class ComponentAdmin(admin.ModelAdmin):
    list_display  = ("name", "model_number", "function", "technical_system", "project", "owner_group", "instance_count")
    list_filter   = ("technical_system", "function", "project", "owner_group")
    search_fields = ("name", "alternate_name", "model_number", "description")
    readonly_fields = ("created_on", "modified_on")
    inlines = [ComponentSourceInline, PropertyValueComponentInline, ComponentInstanceInline, LogComponentInline]
    fieldsets = (
        ("Identity",        {"fields": ("name", "alternate_name", "model_number", "description", "project")}),
        ("Classification",  {"fields": ("technical_system", "function")}),
        ("Ownership",       {"fields": ("owner_user", "owner_group", "group_writeable", "created_by", "created_on", "modified_by", "modified_on"), "classes": ("collapse",)}),
    )

    @admin.display(description="# Instances")
    def instance_count(self, obj):
        return obj.instances.count()

# ── Domain 2: Inventory ───────────────────────────────────────────────────────

@admin.register(ComponentInstance)
class ComponentInstanceAdmin(admin.ModelAdmin):
    list_display  = ("qr_id", "tag", "component", "serial_number", "location", "institution_name", "owner_group")
    list_filter   = ("component__technical_system", "location__institution", "owner_group")
    search_fields = ("qr_id", "tag", "serial_number", "component__name")
    readonly_fields = ("created_on", "modified_on")
    inlines = [PropertyValueInstanceInline, LogInstanceInline]
    fieldsets = (
        ("Identification", {"fields": ("qr_id", "tag", "serial_number", "component")}),
        ("Location",       {"fields": ("location", "description")}),
        ("Ownership",      {"fields": ("owner_user", "owner_group", "group_writeable", "created_by", "created_on", "modified_by", "modified_on"), "classes": ("collapse",)}),
    )

    @admin.display(description="Institution")
    def institution_name(self, obj):
        return obj.location.institution if obj.location else "—"

# ── Domain 3: Designs ─────────────────────────────────────────────────────────

@admin.register(Design)
class DesignAdmin(admin.ModelAdmin):
    list_display  = ("name", "project", "element_count", "owner_group")
    list_filter   = ("project", "owner_group")
    search_fields = ("name", "description")
    readonly_fields = ("created_on", "modified_on")
    inlines = [DesignElementInline, PropertyValueDesignInline, LogDesignInline]
    fieldsets = (
        ("Identity",  {"fields": ("name", "description", "project")}),
        ("Ownership", {"fields": ("owner_user", "owner_group", "group_writeable", "created_by", "created_on", "modified_by", "modified_on"), "classes": ("collapse",)}),
    )

    @admin.display(description="# Elements")
    def element_count(self, obj):
        return obj.elements.count()

@admin.register(DesignElement)
class DesignElementAdmin(admin.ModelAdmin):
    list_display  = ("element_name", "design", "element_type_display", "component", "child_design", "installed_instance", "quantity")
    list_filter   = ("design",)
    search_fields = ("element_name", "design__name", "component__name")
    inlines = [PropertyValueElementInline]

    @admin.display(description="Type")
    def element_type_display(self, obj):
        return obj.element_type()

# ── Cross-domain browsing ─────────────────────────────────────────────────────

@admin.register(LogEntry)
class LogEntryAdmin(admin.ModelAdmin):
    list_display  = ("timestamp", "logged_by", "topic", "short_entry", "component", "component_instance", "design")
    list_filter   = ("topic",)
    search_fields = ("entry",)
    readonly_fields = ("timestamp",)

    @admin.display(description="Entry")
    def short_entry(self, obj):
        return obj.entry[:80]

@admin.register(PropertyValue)
class PropertyValueAdmin(admin.ModelAdmin):
    list_display  = ("property_type", "tag", "value", "units", "component", "component_instance", "design")
    list_filter   = ("property_type__category", "is_dynamic")
    search_fields = ("tag", "value", "property_type__name")

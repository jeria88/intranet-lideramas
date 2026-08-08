from django.contrib import admin

from .models import Ciudad, Contacto, Etapa, Lead, Target, Vertical


class EtapaInline(admin.TabularInline):
    model = Etapa
    extra = 0


@admin.register(Vertical)
class VerticalAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'slug', 'activa', 'creada_en')
    list_filter = ('activa',)
    prepopulated_fields = {'slug': ('nombre',)}


@admin.register(Ciudad)
class CiudadAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'region')
    search_fields = ('nombre',)


@admin.register(Target)
class TargetAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'activo', 'meta_leads_dia', 'total_leads')
    list_filter = ('activo', 'vertical', 'ciudad')
    inlines = [EtapaInline]
    actions = ['crear_kanban']

    @admin.display(description='Leads')
    def total_leads(self, obj):
        return obj.leads.count()

    @admin.action(description='Crear las etapas por defecto')
    def crear_kanban(self, request, queryset):
        for target in queryset:
            target.crear_etapas_por_defecto()
        self.message_user(request, f'Etapas creadas en {queryset.count()} target(s).')


class ContactoInline(admin.TabularInline):
    model = Contacto
    extra = 0
    readonly_fields = ('fecha', 'respondio')


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'target', 'etapa', 'score', 'ultimo_contacto')
    list_filter = ('target__vertical', 'target__ciudad', 'etapa', 'origen')
    search_fields = ('nombre', 'contacto', 'email', 'telefono', 'rbd')
    readonly_fields = ('hash_dedupe', 'score', 'creado_en', 'actualizado_en')
    inlines = [ContactoInline]


@admin.register(Contacto)
class ContactoAdmin(admin.ModelAdmin):
    list_display = ('lead', 'canal', 'respondio', 'fecha', 'enviado_por')
    list_filter = ('canal', 'respondio')
    search_fields = ('lead__nombre', 'enviado', 'respuesta')
    readonly_fields = ('respondio', 'fecha')

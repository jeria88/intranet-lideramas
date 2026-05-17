from django.contrib import admin
from .models import AIAssistant, AIQuery, AIKnowledgeBase
from .utils import index_knowledge_base_file


class AIKnowledgeBaseInline(admin.TabularInline):
    model = AIKnowledgeBase
    extra = 1
    fields = ['name', 'file', 'nivel', 'is_processed']
    readonly_fields = ['is_processed']


@admin.register(AIAssistant)
class AIAssistantAdmin(admin.ModelAdmin):
    list_display = ['name', 'profile_role', 'is_active', 'establishment']
    list_filter = ['profile_role', 'is_active']
    inlines = [AIKnowledgeBaseInline]
    fieldsets = (
        (None, {
            'fields': ('slug', 'name', 'profile_role', 'establishment', 'is_active')
        }),
        ('Contenido IA', {
            'fields': ('system_instruction', 'context_text', 'is_chat_enabled', 'description', 'use_cases', 'image_name'),
            'description': 'Configure las instrucciones y revise el contexto acumulado de los PDFs.'
        }),
    )
    readonly_fields = ['context_text']


@admin.register(AIKnowledgeBase)
class AIKnowledgeBaseAdmin(admin.ModelAdmin):
    list_display = ['name', 'assistant', 'nivel', 'is_processed', 'created_at']
    list_filter = ['is_processed', 'nivel', 'assistant']
    actions = ['index_in_rag']

    def index_in_rag(self, request, queryset):
        total_chunks = 0
        errors = []

        for kb_obj in queryset:
            chunks, error = index_knowledge_base_file(kb_obj)
            if error:
                errors.append(f"{kb_obj.name}: {error}")
            else:
                total_chunks += chunks

        if total_chunks:
            self.message_user(
                request,
                f"{total_chunks} chunks indexados correctamente en el RAG."
            )
        for err in errors:
            self.message_user(request, err, level='error')

    index_in_rag.short_description = "Indexar en RAG (genera embeddings y carga al vector store)"


@admin.register(AIQuery)
class AIQueryAdmin(admin.ModelAdmin):
    list_display = ['user', 'assistant', 'status', 'submitted_at', 'deadline', 'answered_by']
    list_filter = ['status', 'assistant']
    search_fields = ['question', 'answer', 'user__username']
    readonly_fields = ['submitted_at', 'deadline']
    ordering = ['deadline']

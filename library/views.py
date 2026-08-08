from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.management import call_command
import logging

logger = logging.getLogger(__name__)
from django.db.models import Q
from .models import Document, Category
from users.models import User
from users.scoping import establecimientos_de


@login_required
def document_list(request):
    docs = Document.objects.select_related('category', 'author').all()
    categories = Category.objects.all()
    # Filtros
    q = request.GET.get('q', '')
    cat = request.GET.get('category')
    ee = request.GET.get('establishment')
    cargo = request.GET.get('cargo')
    if q:
        docs = docs.filter(Q(title__icontains=q) | Q(description__icontains=q) | Q(materia__icontains=q))
    if cat:
        docs = docs.filter(category__id=cat)
    if ee:
        docs = docs.filter(establishment=ee)
    if cargo:
        docs = docs.filter(cargo_type=cargo)
    # Solo mostrar versión más reciente (sin parent_document = raíz)
    # o con parent_document para ver historial completo
    show_all = request.GET.get('show_all')
    if not show_all:
        docs = docs.filter(parent_document__isnull=True)

    return render(request, 'library/document_list.html', {
        'documents': docs,
        'categories': categories,
        'establishments': establecimientos_de(request.user),
        'roles': User.ROLE_CHOICES,
        'query': q, 
        'selected_category': cat, 
        'selected_establishment': ee, 
        'selected_role': cargo,
    })


@login_required
def document_upload(request):
    if request.method == 'POST':
        from .forms import DocumentForm
        form = DocumentForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                doc = form.save(commit=False)
                doc.author = request.user
                # Asignar establecimiento del usuario y versión inicial automáticamente
                doc.establishment = request.user.establishment
                doc.version = '1.0'
                doc.save()
                messages.success(request, f"Documento '{doc.title}' subido con éxito.")
                logger.info(f"Documento subido: {doc.title} por {request.user.username}")
                return redirect('library:document_list')
            except Exception as e:
                logger.error(f"Error al guardar documento: {str(e)}")
                messages.error(request, f"Error crítico al guardar en la base de datos: {e}")
        else:
            logger.warning(f"Formulario de biblioteca inválido: {form.errors.as_json()}")
            messages.error(request, "Error en el formulario. Por favor revisa los campos.")
    else:
        from .forms import DocumentForm
        form = DocumentForm()
    return render(request, 'library/document_upload.html', {'form': form})


@login_required
def document_detalle(request, pk):
    doc = get_object_or_404(Document, pk=pk)
    versions = Document.objects.filter(
        Q(pk=doc.pk) | Q(parent_document=doc) | Q(parent_document=doc.parent_document, parent_document__isnull=False)
    ).order_by('version')
    return render(request, 'library/document_detalle.html', {'doc': doc, 'versions': versions})


@login_required
def document_edit(request, pk):
    doc = get_object_or_404(Document, pk=pk)
    
    # Seguridad: solo el autor o staff pueden editar
    if doc.author != request.user and not request.user.is_staff:
        messages.error(request, "No tienes permiso para editar este documento.")
        return redirect('library:document_list')

    from .forms import DocumentForm
    if request.method == 'POST':
        form = DocumentForm(request.POST, request.FILES, instance=doc)
        if form.is_valid():
            form.save()
            messages.success(request, f"Documento '{doc.title}' actualizado.")
            return redirect('library:document_list')
    else:
        form = DocumentForm(instance=doc)
    
    return render(request, 'library/document_upload.html', {
        'form': form,
        'is_edit': True,
        'doc': doc
    })


@login_required
def document_delete(request, pk):
    doc = get_object_or_404(Document, pk=pk)
    
    # Seguridad: solo el autor o staff pueden eliminar
    if doc.author != request.user and not request.user.is_staff:
        messages.error(request, "No tienes permiso para eliminar este documento.")
        return redirect('library:document_list')

    if request.method == 'POST':
        title = doc.title
        doc.delete()
        messages.success(request, f"Documento '{title}' eliminado permanentemente.")
        return redirect('library:document_list')
    
    return render(request, 'library/document_confirm_delete.html', {'doc': doc})

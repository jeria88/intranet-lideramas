from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def _set_constraints_immediate(apps, schema_editor):
    """`SET CONSTRAINTS` solo existe en PostgreSQL.

    En SQLite (tests locales, dev sin Postgres) no hay triggers diferidos que
    forzar, así que la operación es un no-op. Antes iba como RunSQL crudo y
    reventaba toda la suite con `OperationalError: near "SET": syntax error`,
    lo que dejaba el proyecto sin forma de correr tests.
    """
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute("SET CONSTRAINTS ALL IMMEDIATE;")


class Migration(migrations.Migration):

    dependencies = [
        ('simce', '0004_texto_revision'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # ── Limpiar datos viejos (orden FK: hijos primero) ────────────
        migrations.RunSQL(
            "DELETE FROM simce_respuestaestudiante;",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            "DELETE FROM simce_alternativa;",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            "DELETE FROM simce_pregunta;",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            "DELETE FROM simce_textoprueba;",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql=(
                "UPDATE simce_prueba SET estado='borrador' "
                "WHERE estado NOT IN ('revision','aprobada','publicada','cerrada','borrador');"
            ),
            reverse_sql=migrations.RunSQL.noop,
        ),

        # Forzar ejecución de triggers diferidos antes de ALTER TABLE (solo PostgreSQL)
        migrations.RunPython(
            _set_constraints_immediate,
            migrations.RunPython.noop,
        ),

        # ── Pregunta: quitar unique_together viejo ────────────────────
        migrations.AlterUniqueTogether(
            name='pregunta',
            unique_together=set(),
        ),

        # ── Pregunta: quitar FK vieja a TextoPrueba ───────────────────
        migrations.RemoveField(
            model_name='pregunta',
            name='texto',
        ),

        # ── Prueba: quitar prompt_usado ───────────────────────────────
        migrations.RemoveField(
            model_name='prueba',
            name='prompt_usado',
        ),

        # ── Crear TextoBiblioteca ─────────────────────────────────────
        migrations.CreateModel(
            name='TextoBiblioteca',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('asignatura', models.CharField(
                    choices=[
                        ('lenguaje',   'Lenguaje y Comunicación'),
                        ('matematica', 'Matemática'),
                        ('ciencias',   'Ciencias Naturales'),
                        ('historia',   'Historia, Geografía y Cs. Sociales'),
                    ],
                    db_index=True, max_length=20,
                )),
                ('tipo_textual', models.CharField(
                    choices=[
                        ('cuento',         'Cuento'),
                        ('fabula',         'Fábula'),
                        ('noticia',        'Noticia'),
                        ('reportaje',      'Reportaje'),
                        ('articulo_cient', 'Artículo Científico'),
                        ('receta',         'Receta'),
                        ('instructivo',    'Manual / Instructivo'),
                        ('afiche',         'Afiche Publicitario'),
                        ('soneto',         'Soneto'),
                        ('oda',            'Oda'),
                        ('discontinuo',    'Texto Informativo Discontinuo'),
                        ('infografia',     'Infografía'),
                        ('carta_formal',   'Carta Formal'),
                        ('carta_director', 'Carta al Director'),
                        ('carta_informal', 'Carta Informal'),
                    ],
                    max_length=20,
                )),
                ('titulo', models.CharField(max_length=200)),
                ('contenido', models.TextField()),
                ('dificultad', models.PositiveSmallIntegerField(
                    choices=[(1, 'Básico'), (2, 'Intermedio'), (3, 'Avanzado')],
                    default=2,
                )),
                ('estado', models.CharField(
                    choices=[
                        ('pendiente',  'Pendiente'),
                        ('aprobado',   'Aprobado'),
                        ('rechazado',  'Rechazado'),
                    ],
                    db_index=True, default='pendiente', max_length=10,
                )),
                ('word_count', models.PositiveIntegerField(default=0)),
                ('char_count', models.PositiveIntegerField(default=0)),
                ('checklist_admin', models.JSONField(default=dict)),
                ('creada_en', models.DateTimeField(auto_now_add=True)),
                ('actualizada_en', models.DateTimeField(auto_now=True)),
                ('creada_por', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='textos_simce',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'verbose_name': 'Texto biblioteca',
                'verbose_name_plural': 'Textos biblioteca',
                'ordering': ['-creada_en'],
            },
        ),

        # ── Crear PreguntaBanco ───────────────────────────────────────
        migrations.CreateModel(
            name='PreguntaBanco',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('enunciado', models.TextField()),
                ('nivel', models.PositiveSmallIntegerField(
                    choices=[(1, '⭐ Inicial'), (2, '⭐⭐ Intermedio'), (3, '⭐⭐⭐ Avanzado')],
                )),
                ('habilidad', models.CharField(max_length=200)),
                ('habilidad_justificacion', models.TextField(blank=True)),
                ('nivel_justificacion', models.TextField(blank=True)),
                ('alternativa_correcta', models.CharField(
                    choices=[('A', 'A'), ('B', 'B'), ('C', 'C'), ('D', 'D')],
                    max_length=1,
                )),
                ('pista_1', models.TextField(blank=True)),
                ('pista_2', models.TextField(blank=True)),
                ('estado', models.CharField(
                    choices=[
                        ('pendiente',  'Pendiente'),
                        ('aprobado',   'Aprobado'),
                        ('rechazado',  'Rechazado'),
                    ],
                    db_index=True, default='pendiente', max_length=10,
                )),
                ('creada_en', models.DateTimeField(auto_now_add=True)),
                ('texto', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='preguntas_banco',
                    to='simce.textobiblioteca',
                )),
            ],
            options={
                'verbose_name': 'Pregunta banco',
                'verbose_name_plural': 'Preguntas banco',
                'ordering': ['nivel', 'creada_en'],
            },
        ),

        # ── Crear AlternativaBanco ────────────────────────────────────
        migrations.CreateModel(
            name='AlternativaBanco',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('letra', models.CharField(
                    choices=[('A', 'A'), ('B', 'B'), ('C', 'C'), ('D', 'D')],
                    max_length=1,
                )),
                ('texto', models.TextField()),
                ('es_correcta', models.BooleanField(default=False)),
                ('justificacion', models.TextField(blank=True)),
                ('pregunta', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='alternativas',
                    to='simce.preguntabanco',
                )),
            ],
            options={
                'verbose_name': 'Alternativa banco',
                'ordering': ['letra'],
            },
        ),
        migrations.AlterUniqueTogether(
            name='alternativabanco',
            unique_together={('pregunta', 'letra')},
        ),

        # ── Crear PruebaTexto ─────────────────────────────────────────
        migrations.CreateModel(
            name='PruebaTexto',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('orden', models.PositiveSmallIntegerField()),
                ('n_nivel1', models.PositiveSmallIntegerField(default=1, verbose_name='Preguntas Inicial')),
                ('n_nivel2', models.PositiveSmallIntegerField(default=1, verbose_name='Preguntas Intermedio')),
                ('n_nivel3', models.PositiveSmallIntegerField(default=3, verbose_name='Preguntas Avanzado')),
                ('prueba', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='prueba_textos',
                    to='simce.prueba',
                )),
                ('texto', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='usos_en_pruebas',
                    to='simce.textobiblioteca',
                )),
            ],
            options={
                'verbose_name': 'Texto en prueba',
                'ordering': ['orden'],
            },
        ),
        migrations.AlterUniqueTogether(
            name='pruebatexto',
            unique_together={('prueba', 'texto')},
        ),

        # ── Crear SimceDocumento ──────────────────────────────────────
        migrations.CreateModel(
            name='SimceDocumento',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nombre', models.CharField(max_length=200)),
                ('asignatura', models.CharField(
                    choices=[
                        ('lenguaje',   'Lenguaje y Comunicación'),
                        ('matematica', 'Matemática'),
                        ('ciencias',   'Ciencias Naturales'),
                        ('historia',   'Historia, Geografía y Cs. Sociales'),
                        ('general',    'General (todas)'),
                    ],
                    default='general', max_length=20,
                )),
                ('file_path', models.CharField(blank=True, max_length=500)),
                ('procesado', models.BooleanField(default=False)),
                ('n_chunks', models.PositiveIntegerField(default=0)),
                ('subido_en', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'verbose_name': 'Documento SIMCE',
                'verbose_name_plural': 'Documentos SIMCE',
                'ordering': ['asignatura', 'nombre'],
            },
        ),

        # ── Crear SimceChunk ──────────────────────────────────────────
        migrations.CreateModel(
            name='SimceChunk',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('asignatura', models.CharField(db_index=True, max_length=20)),
                ('contenido', models.TextField()),
                ('embedding', models.JSONField(blank=True, null=True)),
                ('chunk_index', models.PositiveIntegerField()),
                ('documento', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='chunks',
                    to='simce.simcedocumento',
                )),
            ],
            options={
                'verbose_name': 'Chunk SIMCE',
                'ordering': ['documento', 'chunk_index'],
            },
        ),

        # ── Pregunta: nuevas FKs ──────────────────────────────────────
        migrations.AddField(
            model_name='pregunta',
            name='prueba_texto',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='preguntas',
                to='simce.pruebatexto',
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='pregunta',
            name='desde_banco',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='usos_en_pruebas',
                to='simce.preguntabanco',
            ),
        ),

        # ── Eliminar TextoPrueba (ya vacía) ───────────────────────────
        migrations.DeleteModel(
            name='TextoPrueba',
        ),

        # ── Actualizar choices de Prueba.estado ───────────────────────
        migrations.AlterField(
            model_name='prueba',
            name='estado',
            field=models.CharField(
                choices=[
                    ('generando_textos',    'Generando textos…'),
                    ('generando_preguntas', 'Generando preguntas…'),
                    ('borrador',            'Borrador'),
                    ('error',               'Error'),
                    ('revision',            'En Revisión'),
                    ('aprobada',            'Aprobada'),
                    ('publicada',           'Publicada'),
                    ('cerrada',             'Cerrada'),
                ],
                default='borrador', max_length=22,
            ),
        ),
    ]

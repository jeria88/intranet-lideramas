"""Guardia contra la reentrada de marca de cliente en el producto.

LíderA+ nació como la intranet de un cliente único (una congregación con 8
colegios) y se está convirtiendo en producto. Sin un test que lo vigile, la marca
vuelve sola: un prompt copiado, un default "temporal", un seed de demo.

Qué NO cubre este test, a propósito:
  - `*/migrations/`: son historia ya aplicada. Reescribirlas es peor que la marca.
  - `scratch/`: fuera del producto, conservado a propósito.
  - `ai_modules/eval_results/`: informes de evaluación, no código.
"""
import re
import subprocess
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

# Nombres del cliente original y su vocabulario propio.
PATRONES = [
    r'\bSFA\b',
    r'San Francisco de As',
    r'Franciscan',
    r'Hermanas Terceras',
    r'Congregaci[oó]n',
    r'intranetsfa',
    r'intranet-sfa',
]

# Sedes de ese cliente. Solo se buscan como valor hardcodeado en código Python,
# no en prosa: 'Temuco' es una ciudad real y puede aparecer legítimamente en un
# test o en datos de ejemplo de otra organización.
SEDES = ['TEMUCO', 'LAUTARO', 'RENAICO', 'IMPERIAL', 'ERCILLA', 'ARAUCO', 'ANGOL']

EXCLUIDOS = (
    '/migrations/', '/scratch/', '/.venv/', '/venv/', '/eval_results/',
    '/node_modules/', '/staticfiles/', '/.git/',
    # Este archivo contiene los patrones por definición.
    'tests_marca.py',
)


def _archivos_del_producto():
    raiz = Path(settings.BASE_DIR)
    salida = subprocess.run(
        ['git', 'ls-files', '*.py', '*.html', 'Procfile'],
        cwd=raiz, capture_output=True, text=True, check=False,
    ).stdout.splitlines()
    for relativo in salida:
        if any(x.strip('/') in relativo.split('/') or x in f'/{relativo}' for x in EXCLUIDOS):
            continue
        ruta = raiz / relativo
        if ruta.is_file():
            yield relativo, ruta


class SinMarcaDeClienteTests(SimpleTestCase):
    def test_no_hay_marca_del_cliente_original_en_el_producto(self):
        hallazgos = []
        for relativo, ruta in _archivos_del_producto():
            try:
                texto = ruta.read_text(encoding='utf-8')
            except (UnicodeDecodeError, OSError):
                continue
            for n, linea in enumerate(texto.splitlines(), 1):
                for patron in PATRONES:
                    if re.search(patron, linea, re.IGNORECASE):
                        hallazgos.append(f'{relativo}:{n}  {linea.strip()[:90]}')

        self.assertEqual(
            hallazgos, [],
            'Volvió a entrar marca del cliente original al producto:\n  '
            + '\n  '.join(hallazgos),
        )

    def test_las_sedes_del_cliente_no_estan_hardcodeadas(self):
        """Un catálogo de sedes en el código es la señal de que volvió el enum.

        Se marca solo si aparecen TRES o más en el mismo archivo: una suelta puede
        ser un dato de prueba legítimo; tres juntas son la lista del cliente.
        """
        hallazgos = []
        for relativo, ruta in _archivos_del_producto():
            if not relativo.endswith('.py'):
                continue
            try:
                texto = ruta.read_text(encoding='utf-8')
            except (UnicodeDecodeError, OSError):
                continue
            presentes = {s for s in SEDES if re.search(rf"['\"]{s}['\"]", texto)}
            if len(presentes) >= 3:
                hallazgos.append(f'{relativo}: {sorted(presentes)}')

        self.assertEqual(
            hallazgos, [],
            'Hay un catálogo de sedes de un cliente hardcodeado. Las sedes viven en '
            'la tabla Establecimiento:\n  ' + '\n  '.join(hallazgos),
        )

    def test_el_procfile_no_ejecuta_comandos_de_un_cliente(self):
        procfile = (Path(settings.BASE_DIR) / 'Procfile').read_text(encoding='utf-8')
        for comando in ('archive_sfa_users', 'setup_all_establishments', 'setup_v2_temuco',
                        'setup_v3_temuco', 'setup_utp_temuco'):
            self.assertNotIn(
                comando, procfile,
                f'El Procfile ejecuta "{comando}" en cada deploy: eso reinstala los '
                f'datos de un cliente en cualquier organización nueva.',
            )

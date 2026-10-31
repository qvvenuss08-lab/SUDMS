"""Official SAC document catalog, imported 2026-10-24 without modifying files."""
import json
from pathlib import Path
DATA=json.loads((Path(__file__).parent/'sac_forms.json').read_text(encoding='utf-8'))
SAC_FORM_CATEGORIES=DATA['categories']
SAC_FORM_ITEMS={item['id']:item for group in SAC_FORM_CATEGORIES for item in group['items']}

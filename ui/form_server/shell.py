"""ui/form_server/shell.py — CSS e helper condivisi tra le pagine del form-server.

Estratto da form_server.py: form_server.py stesso importa CSS/STREAMLIT_URL/safe_f
da qui per restare compatibile con le pagine non ancora estratte.
"""
from __future__ import annotations

from ui.form_server.theme import FORM_COLORS

STREAMLIT_URL = "http://localhost:8501"


def safe_f(v, default: float = 0.0) -> float:
    try:
        return float(v or 0)
    except Exception:
        return default


TAB_JS = """
<script>
function switchTab(g,n){
  document.querySelectorAll('[data-tg="'+g+'"]').forEach(b=>b.classList.toggle('active',b.dataset.t===n));
  document.querySelectorAll('[data-pg="'+g+'"]').forEach(p=>p.classList.toggle('active',p.dataset.p===n));
}
</script>"""

_ROOT_VARS_BLOCK = "<style>\n:root{\n" + "\n".join(
    f"  --{name}: {value};" for name, value in FORM_COLORS.items()
) + "\n}\n"

CSS = _ROOT_VARS_BLOCK + """
*,*::before,*::after{box-sizing:border-box}
body{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;background:var(--slate-100);color:var(--slate-800);margin:0;padding:20px 12px 48px;font-size:.94rem}
.card{background:var(--white);border-radius:14px;padding:26px 28px 22px;max-width:720px;margin:0 auto;box-shadow:0 2px 16px var(--black-a07)}
h1{font-size:1.15rem;font-weight:800;margin:0 0 20px;color:var(--slate-800)}
h2{font-size:.82rem;font-weight:800;text-transform:uppercase;letter-spacing:.05em;color:var(--slate-500);margin:22px 0 10px}
label.lbl{display:block;font-weight:600;font-size:.8rem;text-transform:uppercase;letter-spacing:.04em;margin:14px 0 4px;color:var(--slate-500)}
select,input[type=text],input[type=number],input[type=date]{width:100%;padding:9px 11px;border:1px solid var(--slate-300);border-radius:8px;font-size:.93rem;background:var(--white);outline:none;transition:border-color .15s,box-shadow .15s}
select:focus,input:focus{border-color:var(--indigo-500);box-shadow:0 0 0 3px var(--indigo-500-a12)}
input.computed{background:var(--indigo-50)!important;color:var(--indigo-700)!important;cursor:not-allowed}
.row2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.row3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px}
.area-group{display:flex;gap:20px;margin-bottom:6px}
.area-group label{display:flex;align-items:center;gap:7px;font-weight:600;cursor:pointer;font-size:.93rem}
.area-group input[type=radio]{width:16px;height:16px;accent-color:var(--indigo-500)}
.hint{font-size:.76rem;color:var(--slate-400);margin-top:4px}
.check-wrap{display:flex;align-items:flex-start;gap:9px;margin-top:14px;cursor:pointer}
.check-wrap input[type=checkbox]{width:17px;height:17px;margin-top:2px;accent-color:var(--indigo-500);flex-shrink:0}
.check-wrap span{font-size:.87rem;color:var(--slate-700);line-height:1.4}
.btn-add{display:block;width:100%;padding:11px;background:var(--indigo-500);color:var(--white);border:none;border-radius:9px;font-size:.95rem;font-weight:700;cursor:pointer;margin-top:18px;transition:background .15s}
.btn-add:hover{background:var(--indigo-600)}
.btn-confirm{display:block;width:100%;padding:13px;background:var(--emerald-600);color:var(--white);border:none;border-radius:9px;font-size:1rem;font-weight:700;cursor:pointer;margin-top:14px;transition:background .15s}
.btn-confirm:hover{background:var(--emerald-700)}
.btn-confirm:disabled{background:var(--slate-400);cursor:not-allowed}
.section{display:none}
.section.on{display:block}
.alert-err{background:var(--red-50);border:1px solid var(--red-300);border-radius:9px;padding:12px 16px;margin-bottom:18px;color:var(--red-700);font-size:.87rem;line-height:1.5}
.cart-empty{text-align:center;color:var(--slate-400);font-size:.85rem;padding:16px 0}
.cart-table{width:100%;border-collapse:collapse;font-size:.85rem}
.cart-table th{text-align:left;font-size:.73rem;text-transform:uppercase;letter-spacing:.04em;color:var(--slate-400);font-weight:700;padding:0 8px 6px;border-bottom:1px solid var(--slate-200)}
.cart-table td{padding:8px 8px;border-bottom:1px solid var(--slate-100);vertical-align:middle}
.cart-table tr:last-child td{border-bottom:none}
.rm-btn{background:none;border:none;color:var(--red-500);cursor:pointer;font-size:1.1rem;padding:0 4px;line-height:1}
.rm-btn:hover{color:var(--red-700)}
.divider{border:none;border-top:1px solid var(--slate-200);margin:20px 0}
.back-links{margin-top:16px;display:flex;gap:20px}
.back-links a{color:var(--indigo-500);text-decoration:none;font-weight:600;font-size:.88rem}
.back-links a:hover{text-decoration:underline}
.success-icon{font-size:2.5rem;margin-bottom:10px}
.cart-count{font-size:.78rem;font-weight:700;color:var(--indigo-500);float:right;margin-top:2px}
.tabs{display:flex;gap:2px;border-bottom:2px solid var(--slate-200);margin-bottom:20px;margin-top:4px}
.tab-btn{background:none;border:none;border-bottom:3px solid transparent;margin-bottom:-2px;padding:8px 14px;font-size:.87rem;font-weight:600;color:var(--slate-500);cursor:pointer;transition:color .15s,border-color .15s}
.tab-btn.active{color:var(--indigo-500);border-bottom-color:var(--indigo-500)}
.tab-panel{display:none}
.tab-panel.active{display:block}
.preview-box{background:var(--slate-50);border:1px solid var(--slate-200);border-radius:8px;padding:12px 16px;margin:10px 0 14px;font-size:.85rem;line-height:1.6}
.preview-box .prow{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;font-size:.82rem}
.preview-box .plbl{color:var(--slate-500);font-size:.70rem;font-weight:800;text-transform:uppercase;margin-bottom:2px}
.preview-box .pval{font-weight:700;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.preview-details{font-size:.82rem;margin-top:10px;border-top:1px solid var(--slate-200);padding-top:10px}
.preview-details .dr{display:flex;gap:8px;padding:3px 0}
.preview-details .dk{color:var(--slate-500);font-size:.75rem;width:110px;flex-shrink:0}
.preview-details .dv{color:var(--slate-800)}
.metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:14px 0}
.metric{background:var(--slate-50);border:1px solid var(--slate-200);border-radius:8px;padding:10px 14px;text-align:center}
.metric-lbl{font-size:.70rem;text-transform:uppercase;letter-spacing:.04em;color:var(--slate-400);font-weight:700;margin-bottom:4px}
.metric-val{font-size:.95rem;font-weight:800;color:var(--slate-800)}
.alert-warn{background:var(--amber-50);border:1px solid var(--amber-300);border-radius:8px;padding:11px 16px;color:var(--amber-800);font-size:.87rem;margin-bottom:14px}
.alert-ok{background:var(--green-50);border:1px solid var(--green-300);border-radius:8px;padding:11px 16px;color:var(--green-800);font-size:.87rem;margin-bottom:14px}
.btp-fields{display:none;background:var(--sky-50);border:1px solid var(--sky-200);border-radius:8px;padding:16px;margin-top:12px}
.btp-fields.on{display:block}
.table-simple{width:100%;border-collapse:collapse;font-size:.84rem}
.table-simple th{text-align:left;font-size:.71rem;text-transform:uppercase;color:var(--slate-400);font-weight:700;padding:0 8px 8px;border-bottom:1px solid var(--slate-200)}
.table-simple td{padding:8px;border-bottom:1px solid var(--slate-100);color:var(--slate-700)}
.table-simple tr:last-child td{border-bottom:none}
.btn-danger{display:block;width:100%;padding:13px;background:var(--red-600);color:var(--white);border:none;border-radius:9px;font-size:1rem;font-weight:700;cursor:pointer;margin-top:14px;transition:background .15s}
.btn-danger:hover{background:var(--red-700)}
.btn-danger:disabled{background:var(--slate-400);cursor:not-allowed}
.edit-section{display:none}
.edit-section.on{display:block}
</style>
"""

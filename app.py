from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

import engine


APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"

st.set_page_config(page_title="Meal planner", page_icon="🍽️", layout="wide")
st.title("🍽️ Meal planner (HelloFresh)")

# --- Chargement des recettes pour proposer une sélection ---
try:
    recettes = json.loads((DATA_DIR / "recettes_hellofresh.txt").read_text(encoding="utf-8"))
    all_names = sorted({r.get("name") for r in recettes if r.get("name")})
except Exception as e:
    st.error(f"Impossible de lire data/recettes_hellofresh.txt : {e}")
    st.stop()

DEFAULT_SELECTION = [
    "Bowl de boulgour aux légumes rôtis",
    "Blanquette de poulet réconfortante",
    "Nouilles sautées au bœuf haché",
    "Velouté de chou-fleur & parmesan AOP",
]

with st.sidebar:
    st.header("Paramètres")
    personnes = st.number_input("Nombre de personnes", min_value=1, max_value=10, value=4, step=1)
    selection = st.multiselect("Recettes à cuisiner", options=all_names, default=[n for n in DEFAULT_SELECTION if n in all_names])
    update_provisions = st.checkbox("Mettre à jour le placard (provisions.txt) + générer courses_placard.txt", value=False)

    run = st.button("Générer 🧾", type="primary", use_container_width=True)

if not run:
    st.info("Choisis tes recettes à gauche, puis clique sur **Générer**.")
    st.stop()

out = engine.run(
    selection=selection,
    personnes=int(personnes),
    data_dir=DATA_DIR,
    update_provisions=bool(update_provisions),
)

col1, col2 = st.columns([1, 1], gap="large")

with col1:
    st.subheader("Courses (après déduction du placard)")
    st.json(out.get("liste_courses") or {})

    if out.get("unknown_global_pretty"):
        st.warning("Ingrédients inconnus (à compléter dans ingredients_infos.txt) :")
        st.write(out["unknown_global_pretty"])

with col2:
    st.subheader("Placard utilisé")
    st.json(out.get("pantry_used") or {})

st.subheader("Logs (sortie du notebook)")
st.code(out.get("log", ""), language="text")

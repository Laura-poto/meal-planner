from pathlib import Path
import streamlit as st
import pandas as pd
import unicodedata
import html
import engine


def _upper_no_accents(s: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    return s.upper()

def format_courses(liste_courses: dict) -> str:
    """
    Transforme la structure dict {rayon: {label: {val, unit, recipes, ...}}}
    en texte lisible style notebook.
    """
    lines = []
    # ordre de rayons : Marché en premier si présent, sinon tri alpha
    rayons = list(liste_courses.keys())
    rayons_sorted = sorted(rayons, key=lambda r: (0 if r.lower() in ["marché","marche"] else 1, r.lower()))
    for rayon in rayons_sorted:
        header = _upper_no_accents(rayon)
        lines.append(f"**{header}**")
        items = liste_courses[rayon] or {}
        # tri : indispensable d'abord, puis alpha
        def _k(item):
            label, d = item
            return (0 if d.get("indispensable") else 1, label.lower())
        for label, d in sorted(items.items(), key=_k):
            val = d.get("val")
            unit = d.get("unit") or ""
            if val is None:
                qty = ""
            else:
                qty = f"{val} {unit}".strip()
            recipes = d.get("recipes") or []
            n = len(recipes)
            recettes_txt = " / ".join(recipes)
            lines.append(f"{label} : {qty}  — dans : {n} recette(s) ({recettes_txt})")
        lines.append("")  # blank line
    return "\n".join(lines).strip()


st.set_page_config(page_title="Meal Planner", layout="wide")
st.title("🍽️ Meal Planner")

DATA_DIR = Path("data")

# 1) Matching
match = engine.compute_matching(DATA_DIR)

st.subheader("📊 Matching des recettes (marché / placard)")

df = pd.DataFrame(match["scored"])

# Renommage colonnes (voir section suivante)
df = df.rename(columns={
    "category": "catégorie",
    "name": "nom",
    "score_market": "taux de match marché",
    "score_pantry": "taux de match placard",
    "ok_market": "OK marché",
    "ok_pantry": "OK placard",
    "manque_market": "manque marché",
    "manque_pantry": "manque placard",
})

cols = ["catégorie", "nom", "taux de match marché", "OK marché", "manque marché", "link"]
cols = [c for c in cols if c in df.columns]  # sécurité

# On veut afficher les colonnes sans la catégorie (affichée en titre)
# et ne pas afficher explicitement la colonne 'link' :
cols_sub = [c for c in cols if c != "catégorie"]  # la catégorie sera dans le sous-titre, pas dans le tableau
# Remplace la section de tri des catégories par ton ordre personnalisé
CUSTOM_CATEGORY_ORDER = [
    "🍗 poulet",
    "🥩 boeuf",
    "🌮 boeuf haché",
    "🍖 porc",
    "🦆 canard",
    "🍝 pâtes végé",
    "🥕 végé",
    "🍜 soupe",
    "🥧 tarte",
    "🥬 salade",
    "🍣 saumon",
    "🐟 poisson blanc",
    "🦐 crevettes"
]

order_map = {c: i for i, c in enumerate(CUSTOM_CATEGORY_ORDER)}

# Trier les catégories selon CUSTOM_CATEGORY_ORDER, les autres à la fin
categories = sorted(
    df["catégorie"].dropna().unique(),
    key=lambda c: order_map.get(c, 999)
)

for cat in categories:
    st.markdown(f"### {cat.upper()}") 
    sdf = df[df["catégorie"] == cat]

    # hauteur auto (évite un gros tableau vide)
    h = min(520, 38 * (len(sdf) + 1) + 20)

    # Préparer les colonnes à afficher : on ne montre pas explicitement la
    # colonne 'link'. Si elle existe, on transforme la colonne 'nom' en
    # liens HTML et on affiche un tableau HTML (avec les ancres <a>), sinon
    # on affiche un data_editor simple.
    visible_cols = [c for c in cols_sub if c != "link"]

    # Construire un DataFrame pour affichage (avec ou sans liens)
    if "link" in sdf.columns:
        df_display = sdf[visible_cols].copy()

        def _make_anchor(row):
            url = row.get("link", "")
            name = row.get("nom", "")
            name_escaped = html.escape(str(name))
            url_escaped = html.escape(str(url))
            if pd.isna(url) or url == "":
                return name_escaped
            return f'<a href="{url_escaped}" target="_blank" rel="noopener noreferrer">{name_escaped}</a>'

        if "nom" in df_display.columns:
            df_display["nom"] = sdf.apply(_make_anchor, axis=1)
    else:
        df_display = sdf[visible_cols].copy()

    # Nettoyer les colonnes contenant des listes pour enlever crochets
    for col in ["OK marché", "manque marché"]:
        if col in df_display.columns:
            def _clean_cell(v):
                if isinstance(v, (list, tuple, set)):
                    return ", ".join(map(str, v))
                if pd.isna(v):
                    return ""
                s = str(v)
                # retire crochets s'ils existent dans la représentation
                if s.startswith("[") and s.endswith("]"):
                    return s[1:-1]
                return s
            df_display[col] = df_display[col].apply(_clean_cell)

    # Générer HTML et appliquer CSS pour aligner les tableaux
    html_table = df_display.to_html(escape=False, index=False)
    html_table = html_table.replace('class="dataframe"', 'class="mealplanner"')

    # CSS : mise en page et alignement. On construit un seul <style> pour
    # éviter que le CSS soit affiché comme du texte.
    base_css = (
        "table.mealplanner { width:100%; border-collapse:collapse; table-layout:fixed; }"
        "table.mealplanner th, table.mealplanner td { padding:6px; text-align:left; vertical-align:middle; border-bottom:1px solid #ddd; }"
        "table.mealplanner th { background:#f9f9f9; }"
    )

    # Centrer les colonnes numériques/OK/manque si présentes
    center_cols = ["taux de match marché", "OK marché", "manque marché"]
    extra_css_lines = []
    for col in center_cols:
        if col in df_display.columns:
            idx = list(df_display.columns).index(col) + 1
            extra_css_lines.append(f'table.mealplanner td:nth-child({idx}), table.mealplanner th:nth-child({idx}) {{ text-align:center; }}')

    style_content = base_css + ("\n" + "\n".join(extra_css_lines) if extra_css_lines else "")
    css = f"<style>{style_content}</style>"

    st.markdown(css + html_table, unsafe_allow_html=True)

st.divider()

# 2) Choix + courses
st.subheader("✅ Choisir les recettes et générer les courses")

options = [r["name"] for r in match["scored"]]  # on propose les recettes filtrées
selection = st.multiselect("Recettes", options=options, default=[])

personnes = st.number_input("Nombre de personnes", min_value=1, max_value=12, value=4, step=1)
update_prov = st.checkbox("Mettre à jour le placard (provisions.txt) et générer courses_placard.txt", value=False)

if st.button("Générer les courses"):
    if not selection:
        st.error("Choisis au moins une recette.")
    else:
        out = engine.compute_courses(DATA_DIR, selection, int(personnes), update_provisions=update_prov)
        st.success("Courses générées.")
        st.markdown(format_courses(out["liste_courses"]).replace("\n", "  \n"))
        with st.expander("Voir la version JSON (debug)"):
            st.json(out["liste_courses"])
        with st.expander("Voir détails placard (consommation / utilisé)"):
            st.json(out["pantry_used"])

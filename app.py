import json
import math
import os
import random
from collections import Counter
import pandas as pd
import requests
from dash import Dash, html, dcc, Input, Output, callback

API_KEY = os.environ.get("PRIM_API_KEY", "bOLm29LnPhUVdbPLWfLzodpT0XI9xrQ4")

# ============================================================
# CHARTE VISUELLE COMMUNE
# ============================================================
COULEUR_FOND = "#F2EFEA"          # base du degrade de fond (le degrade est defini en CSS, index_string)
COULEUR_FOND_CARTE = "#FFFFFF"
COULEUR_TEXTE = "#14131A"         # noir profond, legerement bleute (esprit signaletique)
COULEUR_TEXTE_SECONDAIRE = "#6E6C78"  # gris neutre
COULEUR_LIGNE = "#14131A"         # points noirs (marqueurs), pas les lignes colorees

# --- RESERVE : rubrique "Perturbations" -- NE PAS CHANGER, NE PAS REUTILISER AILLEURS ---
COULEUR_PERTURBATION_KO = "#D8392C"   # rouge - etat "perturbee" (texte + badge), inchange depuis le debut du projet
COULEUR_PERTURBATION_OK = "#2E8B57"   # vert - etat "OK" (badge), inchange depuis le debut du projet

# --- Palette inspiree directement de la photo de reference (plan de transit PBS) ---
MUR_BLEU = "#2F5C8A"          # bleu du mur carrele (zone de fond derriere les cadres) + cadre "Carte" (le hub)
CADRE_CORAIL = "#FF6F59"      # ligne "P"
CADRE_CIEL = "#4F9DC4"        # ligne "B"
CADRE_JAUNE = "#FFC93C"       # ligne "S"
CADRE_LIME = "#A8C43C"        # ligne "K"

FONT_TITRE = "'Archivo', 'Helvetica Neue', Arial, sans-serif"
NB_ETAPES_ANIMATION = 50
DUREE_ETAPE_MS = 30


def enveloppe_ticket(contenu, couleur_bande=None, bande_css=None, span_complet=False, padding="40px 44px 44px",
                      initiale=None, hub=False):
    """Le cadre unique du site, un vrai 'cadre photo' epais colore pose sur le mur de station
    (comme l'affiche de reference : cadre epais + interieur blanc). Meme forme pour TOUT le
    contenu (carte, graphiques, textes, chiffres) ; seules la couleur du cadre, sa taille et
    son contenu different. La pastille "initiale" rappelle les numeros/lettres de ligne."""
    couleur_principale = couleur_bande or MUR_BLEU
    epaisseur = "9px"

    entete = []
    if hub:
        # Le cadre "Carte" est le hub du reseau : double-cercle + petites pastilles
        # (echo purement decoratif des 2 fonctionnalites internes "Lignes" et "Perturbations",
        # qui gardent elles-memes leur style/couleur d'origine, non modifie)
        entete.append(html.Div(
            style={"display": "flex", "alignItems": "center", "gap": "10px", "marginBottom": "18px"},
            children=[
                html.Div(style={
                    "width": "30px", "height": "30px", "borderRadius": "50%",
                    "border": f"4px solid {COULEUR_LIGNE}", "backgroundColor": "#FFFFFF",
                    "position": "relative",
                }, children=html.Div(style={
                    "position": "absolute", "top": "6px", "left": "6px",
                    "width": "10px", "height": "10px", "borderRadius": "50%",
                    "backgroundColor": COULEUR_LIGNE,
                })),
                html.Div(style={
                    "width": "20px", "height": "20px", "borderRadius": "50%",
                    "backgroundColor": "#9C9C9C", "border": f"2px solid {COULEUR_LIGNE}",
                }),
                html.Div(style={
                    "width": "20px", "height": "20px", "borderRadius": "50%",
                    "backgroundColor": COULEUR_PERTURBATION_OK, "border": f"2px solid {COULEUR_LIGNE}",
                }),
            ],
        ))
    elif initiale:
        entete.append(html.Div(
            initiale,
            style={
                "width": "34px", "height": "34px", "borderRadius": "50%",
                "backgroundColor": couleur_principale, "border": f"2.5px solid {COULEUR_LIGNE}",
                "color": "#FFFFFF", "fontWeight": "800", "fontSize": "1rem",
                "display": "flex", "alignItems": "center", "justifyContent": "center",
                "marginBottom": "14px",
            },
        ))

    return html.Div(
        className="ticket",
        style={
            "backgroundColor": couleur_principale,
            "borderRadius": "18px",
            "padding": epaisseur,
            "gridColumn": "1 / -1" if span_complet else None,
        },
        children=html.Div(
            style={
                "backgroundColor": "#FFFFFF",
                "borderRadius": "11px",
                "border": f"2px solid {COULEUR_LIGNE}",
            },
            children=html.Div(
                [*entete, contenu],
                style={"padding": padding, "fontFamily": FONT_TITRE},
            ),
        ),
    )

# ============================================================
# DONNEES COMMUNES AUX DEUX BLOCS
# ============================================================
lignes_ferrees_df = pd.read_csv("lignes_ferrees_idf.csv", encoding="utf-8-sig")
lignes_valides = set(lignes_ferrees_df["ID_Line"])
nom_ligne = dict(zip(lignes_ferrees_df["ID_Line"], lignes_ferrees_df["Name_Line"]))
couleur_hex_ligne = dict(zip(lignes_ferrees_df["ID_Line"], lignes_ferrees_df["ColourWeb_hexa"]))
picto_ligne = dict(zip(lignes_ferrees_df["ID_Line"], lignes_ferrees_df["Picto"]))


def hex_vers_rgb(hex_str, defaut=(150, 150, 150)):
    """Convertit une couleur hexadecimale (ex. '0055c8') en [R, G, B]."""
    if not hex_str or not isinstance(hex_str, str):
        return list(defaut)
    hex_str = hex_str.strip().lstrip("#")
    if len(hex_str) != 6:
        return list(defaut)
    try:
        return [int(hex_str[i:i+2], 16) for i in (0, 2, 4)]
    except ValueError:
        return list(defaut)

df_reference = pd.read_csv("table_finale_carte_v2.csv")
df_reference = df_reference[df_reference["lignes_concernees"].notna() & (df_reference["lignes_concernees"] != "")]

# Chemins reels (avec arrets intermediaires + vrais horaires GTFS), issus de construire_chemins_reels.py
try:
    with open("chemins_reels_flux.json", encoding="utf-8") as f:
        _chemins_bruts = json.load(f)
    chemins_reels = {c["index_flux"]: c for c in _chemins_bruts if c.get("chemin_reel")}
    print(f"{len(chemins_reels)} chemins reels charges")
except FileNotFoundError:
    chemins_reels = {}
    print("chemins_reels_flux.json introuvable -> tous les trajets utiliseront l'ancienne methode (ligne directe)")

compte_lignes = Counter()
for s in df_reference["lignes_concernees"]:
    for l in s.split(";"):
        compte_lignes[l] += 1

def option_ligne(lid):
    """Construit le label du selecteur : logo officiel + nom, avec repli sur le nom seul si pas de logo."""
    picto_url = picto_ligne.get(lid)
    a_un_logo = isinstance(picto_url, str) and picto_url.startswith("http")
    return {
        "label": html.Div(
            style={"display": "flex", "alignItems": "center", "gap": "8px"},
            children=[
                html.Img(src=picto_url, style={"height": "22px", "width": "22px", "objectFit": "contain", "flexShrink": "0"})
                if a_un_logo else None,
                html.Span(nom_ligne.get(lid, lid)),
            ],
        ),
        "value": lid,
    }


lignes_options = [option_ligne(lid) for lid in sorted(compte_lignes, key=lambda x: -compte_lignes[x])]
lignes_par_defaut = [lid for lid, _ in compte_lignes.most_common(3)]

LOOP_LENGTH = 3000
VITESSE_TRAJET = 3200
DUREE_MIN = 150
DUREE_MAX = 2600


# ============================================================
# BLOC 1 : CARTE EN DIRECT
# ============================================================

def get_lignes_perturbees():
    url = "https://prim.iledefrance-mobilites.fr/marketplace/disruptions_bulk/disruptions/v2"
    headers = {"apiKey": API_KEY}
    try:
        response = requests.get(url, headers=headers, timeout=15)
        data = response.json()
    except Exception as e:
        print("Erreur lors de l'appel a l'API perturbations :", e)
        return set()

    lignes_touchees = set()
    for d in data.get("disruptions", []):
        for section in d.get("impactedSections", []):
            line_id = section.get("lineId", "")
            if line_id.startswith("line:IDFM:"):
                ligne = line_id.replace("line:IDFM:", "")
                if ligne in lignes_valides:
                    lignes_touchees.add(ligne)
    return lignes_touchees


DUREE_PAUSE_ARRET = 45  # pause nettement visible (env. 0,35 seconde a l'ecran) a chaque arret intermediaire


def inserer_pauses(path, timestamps):
    """Duplique chaque arret intermediaire pour creer une vraie pause (immobilite) avant de repartir."""
    if len(path) < 3:
        return path, timestamps
    nouveau_path = [path[0]]
    nouveau_ts = [timestamps[0]]
    decalage = 0
    for i in range(1, len(path)):
        nouveau_path.append(path[i])
        nouveau_ts.append(timestamps[i] + decalage)
        if i < len(path) - 1:  # pas de pause au terminus final
            decalage += DUREE_PAUSE_ARRET
            nouveau_path.append(path[i])  # meme position, dupliquee
            nouveau_ts.append(timestamps[i] + decalage)
    return nouveau_path, nouveau_ts


def construire_trips(lignes_perturbees, lignes_selectionnees):
    df = df_reference.copy()
    selection = set(lignes_selectionnees) if lignes_selectionnees else None
    if selection:
        df = df[df["lignes_concernees"].apply(lambda s: bool(set(s.split(";")) & selection))]
    if df.empty:
        return [], 0, 0

    def est_perturbe(lignes_str):
        lignes_du_flux = set(lignes_str.split(";"))
        if selection:
            lignes_du_flux = lignes_du_flux & selection
        return bool(lignes_du_flux & lignes_perturbees)

    trips = []
    nb_perturbes = 0
    random.seed(42)

    for idx, row in df.iterrows():
        lon1, lat1 = float(row["lon_origine"]), float(row["lat_origine"])
        lon2, lat2 = float(row["lon_destination"]), float(row["lat_destination"])

        perturbe = est_perturbe(row["lignes_concernees"])
        if perturbe:
            nb_perturbes += 1

        lignes_du_flux = sorted(row["lignes_concernees"].split(";"))
        if selection:
            lignes_du_flux = sorted(set(lignes_du_flux) & selection) or lignes_du_flux
        ligne_representative = lignes_du_flux[0]
        couleur = hex_vers_rgb(couleur_hex_ligne.get(ligne_representative))

        chemin_reel = chemins_reels.get(idx)

        if chemin_reel and chemin_reel["path"]:
            # --- Vrai chemin avec arrets intermediaires + vrai rythme GTFS ---
            path_brut = chemin_reel["path"]
            temps_cumules = chemin_reel.get("temps_cumules_secondes")
            nb_pauses = max(0, len(path_brut) - 2)  # pas de pause au premier ni au dernier arret
            budget_pauses = nb_pauses * DUREE_PAUSE_ARRET

            if temps_cumules and len(temps_cumules) == len(path_brut):
                duree_reelle = max(temps_cumules[-1], 1)
                # L'echelle tient compte du budget des pauses, pour que le total (trajet + pauses)
                # reste dans nos bornes d'animation habituelles
                budget_trajet = max(DUREE_MIN, min(DUREE_MAX, duree_reelle + budget_pauses)) - budget_pauses
                budget_trajet = max(budget_trajet, 20)
                echelle = budget_trajet / duree_reelle
                timestamps_brutes = [t * echelle for t in temps_cumules]
            else:
                longueur = math.sqrt((lon2 - lon1) ** 2 + (lat2 - lat1) ** 2) or 0.0001
                duree = max(DUREE_MIN, min(DUREE_MAX, longueur * VITESSE_TRAJET))
                n = len(path_brut)
                timestamps_brutes = [duree * i / (n - 1) for i in range(n)]

            path, timestamps_relatives = inserer_pauses(path_brut, timestamps_brutes)
            duree_totale = timestamps_relatives[-1]
            offset = random.randint(0, max(1, int(LOOP_LENGTH - duree_totale - 1)))
            timestamps = [offset + t for t in timestamps_relatives]
        else:
            # --- Repli : pas de chemin reel dispo pour ce flux, ancienne methode (ligne directe courbee) ---
            dx, dy = lon2 - lon1, lat2 - lat1
            longueur = math.sqrt(dx**2 + dy**2) or 0.0001
            perp_x, perp_y = -dy / longueur, dx / longueur
            bombement = longueur * 0.06
            mid_lon = (lon1 + lon2) / 2 + perp_x * bombement
            mid_lat = (lat1 + lat2) / 2 + perp_y * bombement
            path = [[lon1, lat1], [mid_lon, mid_lat], [lon2, lat2]]
            duree = max(DUREE_MIN, min(DUREE_MAX, longueur * VITESSE_TRAJET))
            offset = random.randint(0, max(1, int(LOOP_LENGTH - duree - 1)))
            timestamps = [offset, offset + duree / 2, offset + duree]

        trips.append({
            "path": path,
            "timestamps": timestamps,
            "color": couleur,
            "width": max(1, math.log10(float(row["flux"])) * 1.3),
        })

    return trips, nb_perturbes, len(trips)


def construire_html_animation(trips):
    trips_json = json.dumps(trips)
    return f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<script src="https://unpkg.com/deck.gl@8.9.28/dist.min.js"></script>
<style>
  html, body {{ margin: 0; padding: 0; width: 100vw; height: 100vh; background: #f5f5f0; overflow: hidden; }}
  #map {{ position: absolute; top: 0; left: 0; width: 100vw; height: 100vh; }}
</style>
</head>
<body>
<div id="map"></div>
<script>
  const TRIPS = {trips_json};
  const LOOP_LENGTH = {LOOP_LENGTH};
  let time = 0;

  const {{DeckGL, TileLayer, BitmapLayer, ScatterplotLayer}} = deck;

  function positionActuelle(trip, t) {{
    const ts = trip.timestamps;
    if (t < ts[0] || t > ts[ts.length - 1]) return null;
    for (let i = 0; i < ts.length - 1; i++) {{
      if (t >= ts[i] && t <= ts[i + 1]) {{
        const frac = (t - ts[i]) / (ts[i + 1] - ts[i]);
        const p0 = trip.path[i], p1 = trip.path[i + 1];
        return [p0[0] + (p1[0] - p0[0]) * frac, p0[1] + (p1[1] - p0[1]) * frac];
      }}
    }}
    return null;
  }}

  function getLayers(currentTime) {{
    const points = [];
    for (const trip of TRIPS) {{
      const pos = positionActuelle(trip, currentTime);
      if (pos) {{
        points.push({{position: pos, color: trip.color, radius: trip.width * 2}});
      }}
    }}
    return [
      new TileLayer({{
        id: 'basemap',
        data: 'https://basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}.png',
        minZoom: 0, maxZoom: 19, tileSize: 256,
        renderSubLayers: props => {{
          const {{boundingBox}} = props.tile;
          return new BitmapLayer(props, {{
            data: null, image: props.data,
            bounds: [boundingBox[0][0], boundingBox[0][1], boundingBox[1][0], boundingBox[1][1]]
          }});
        }}
      }}),
      new ScatterplotLayer({{
        id: 'points', data: points,
        getPosition: d => d.position, getFillColor: d => d.color, getRadius: d => d.radius,
        radiusUnits: 'pixels', radiusMinPixels: 3, opacity: 0.9,
      }})
    ];
  }}

  const deckgl = new DeckGL({{
    container: 'map', mapStyle: null,
    initialViewState: {{longitude: 2.35, latitude: 48.85, zoom: 9, pitch: 0, bearing: 0}},
    controller: true, layers: getLayers(0)
  }});

  function animate() {{
    time = (time + 2) % LOOP_LENGTH;
    deckgl.setProps({{layers: getLayers(time)}});
    window.requestAnimationFrame(animate);
  }}
  animate();
</script>
</body>
</html>
"""


def layout_bloc1():
    contenu = html.Div([
        html.H1(
            "Flux de mobilité en Île-de-France",
            style={"color": COULEUR_TEXTE, "textAlign": "center", "marginBottom": "0",
                   "fontSize": "2.4rem", "fontWeight": "900", "letterSpacing": "-0.01em"}
        ),
        html.P(
            id="texte-perturbations",
            style={"color": COULEUR_PERTURBATION_KO, "textAlign": "center", "fontSize": "1rem", "fontWeight": "600",
                   "marginTop": "10px", "marginBottom": "24px"}
        ),
        html.Div(
            style={"display": "flex", "gap": "20px"},
            children=[
                html.Div(
                    style={"width": "240px", "paddingRight": "20px", "borderRight": "1px solid #E7E5DC"},
                    children=[
                        html.Div("Lignes à afficher", style={
                            "color": COULEUR_TEXTE_SECONDAIRE, "fontSize": "0.8rem", "textTransform": "uppercase",
                            "letterSpacing": "0.1em", "marginBottom": "12px", "fontWeight": "600",
                        }),
                        dcc.Dropdown(
                            id="selecteur-lignes",
                            options=lignes_options,
                            value=lignes_par_defaut,
                            multi=True,
                            placeholder="Choisis une ou plusieurs lignes...",
                            style={"color": "black"}
                        ),
                    ],
                ),
                html.Iframe(
                    id="carte-iframe",
                    style={"flex": "1", "height": "70vh", "border": "none", "borderRadius": "14px"}
                ),
                html.Div(
                    id="panneau-lignes",
                    style={
                        "width": "240px", "height": "70vh", "overflowY": "auto",
                        "paddingLeft": "20px", "borderLeft": "1px solid #E7E5DC",
                    },
                ),
            ],
        ),
        dcc.Interval(id="minuteur-refresh", interval=90 * 1000, n_intervals=0),
    ])
    return html.Div(
        style={"background": "transparent", "padding": "24px", "maxWidth": "1360px", "margin": "0 auto"},
        children=[
            enveloppe_ticket(
                contenu,
                couleur_bande=MUR_BLEU,
                hub=True,
                span_complet=False,
            ),
        ],
    )


def construire_panneau_lignes(lignes_perturbees, lignes_selectionnees):
    """Petit panneau : pastille de couleur officielle + statut OK/perturbee pour chaque ligne affichee."""
    lignes_a_afficher = lignes_selectionnees if lignes_selectionnees else [lid for lid, _ in compte_lignes.most_common(10)]

    blocs = [html.Div("Lignes affichées", style={
        "color": COULEUR_TEXTE_SECONDAIRE, "fontSize": "0.85rem", "textTransform": "uppercase",
        "letterSpacing": "0.1em", "marginBottom": "12px",
    })]

    for lid in lignes_a_afficher:
        hex_couleur = couleur_hex_ligne.get(lid)
        couleur_css = f"#{hex_couleur}" if hex_couleur else "#999"
        est_perturbee = lid in lignes_perturbees
        badge = "⚠ Perturbée" if est_perturbee else "✓ OK"
        couleur_badge = COULEUR_PERTURBATION_KO if est_perturbee else COULEUR_PERTURBATION_OK

        blocs.append(html.Div(
            style={"display": "flex", "alignItems": "center", "marginBottom": "10px", "gap": "8px"},
            children=[
                html.Div(style={
                    "width": "14px", "height": "14px", "borderRadius": "50%",
                    "backgroundColor": couleur_css, "flexShrink": "0",
                }),
                html.Div(nom_ligne.get(lid, lid), style={
                    "color": COULEUR_TEXTE, "fontSize": "0.9rem", "flex": "1",
                }),
            ],
        ))
        blocs.append(html.Div(badge, style={
            "color": couleur_badge, "fontSize": "0.75rem", "marginBottom": "12px", "marginLeft": "22px",
        }))

    return blocs


@callback(
    Output("carte-iframe", "srcDoc"),
    Output("texte-perturbations", "children"),
    Output("panneau-lignes", "children"),
    Input("minuteur-refresh", "n_intervals"),
    Input("selecteur-lignes", "value"),
)
def rafraichir_carte(n, lignes_selectionnees):
    lignes_perturbees = get_lignes_perturbees()
    trips, nb_perturbes, total = construire_trips(lignes_perturbees, lignes_selectionnees)
    carte_html = construire_html_animation(trips)
    texte = f"{len(lignes_perturbees)} lignes sur {len(lignes_valides)} connaissent une perturbation en ce moment."
    panneau = construire_panneau_lignes(lignes_perturbees, lignes_selectionnees)
    return carte_html, texte, panneau


# ============================================================
# BLOC 2 : ANALYSE (8 INDICATEURS)
# ============================================================

def carte_chiffre(id_prefix, titre, valeur_cible, format_valeur, sous_texte, recit=None, note=None, couleur=CADRE_CORAIL):
    return html.Div(
        style={"display": "flex", "alignItems": "flex-start", "gap": "22px"},
        children=[
            html.Div(style={
                "width": "18px", "height": "18px", "borderRadius": "50%",
                "backgroundColor": "#FFFFFF", "border": f"4px solid {COULEUR_LIGNE}",
                "marginTop": "6px", "flexShrink": "0",
            }),
            html.Div(style={"flex": "1", "minWidth": "0"}, children=[
                html.Div(titre, style={
                    "color": COULEUR_TEXTE_SECONDAIRE, "fontSize": "0.85rem", "letterSpacing": "0.1em",
                    "textTransform": "uppercase", "marginBottom": "10px", "fontWeight": "600",
                }),
                html.Div(id=f"{id_prefix}-valeur", children=format_valeur(0), style={
                    "color": COULEUR_TEXTE, "fontSize": "4rem", "fontWeight": "700", "lineHeight": "1",
                    "letterSpacing": "-0.02em",
                }),
                html.Div(sous_texte, style={
                    "color": couleur, "fontSize": "1.1rem", "marginTop": "12px", "fontWeight": "700",
                }),
                html.Div(recit, style={
                    "color": COULEUR_TEXTE, "fontSize": "0.95rem", "marginTop": "18px",
                    "lineHeight": "1.6", "borderTop": "1px solid #E7E5DC", "paddingTop": "16px",
                }) if recit else None,
                html.Div(note or "", style={
                    "color": COULEUR_TEXTE_SECONDAIRE, "fontSize": "0.75rem", "marginTop": "14px",
                }) if note else None,
                dcc.Interval(id=f"{id_prefix}-interval", interval=DUREE_ETAPE_MS, n_intervals=0, max_intervals=NB_ETAPES_ANIMATION),
                dcc.Store(id=f"{id_prefix}-cible", data=valeur_cible),
            ]),
        ],
    )


def enregistrer_callback_compteur(id_prefix, format_valeur):
    @callback(
        Output(f"{id_prefix}-valeur", "children"),
        Input(f"{id_prefix}-interval", "n_intervals"),
        Input(f"{id_prefix}-cible", "data"),
    )
    def animer(n, cible):
        n_borne = min(n, NB_ETAPES_ANIMATION)
        return format_valeur(cible * n_borne / NB_ETAPES_ANIMATION)


def carte_classement(titre, items, sous_texte=None, recit=None, note=None, couleur=CADRE_JAUNE, unite="", format_valeur=None, echelle_max=None):
    valeur_max = echelle_max if echelle_max else max(v for _, v in items)
    lignes = []
    for nom, valeur in items:
        largeur_pct = (valeur / valeur_max) * 100
        lignes.append(
            html.Div(
                style={"marginBottom": "18px"},
                children=[
                    html.Div(
                        style={"display": "flex", "justifyContent": "space-between", "marginBottom": "6px", "alignItems": "baseline"},
                        children=[
                            html.Span(nom, style={"color": COULEUR_TEXTE, "fontSize": "1rem", "fontWeight": "500"}),
                            html.Span(format_valeur(valeur) if format_valeur else f"{valeur:,.0f}{unite}".replace(",", " "), style={"color": COULEUR_TEXTE, "fontSize": "1.1rem", "fontWeight": "700"}),
                        ],
                    ),
                    html.Div(
                        style={"backgroundColor": "#E7E5DC", "height": "12px", "width": "100%", "borderRadius": "6px", "overflow": "hidden"},
                        children=html.Div(style={
                            "backgroundColor": couleur, "height": "100%",
                            "width": f"{largeur_pct}%", "borderRadius": "6px",
                        }),
                    ),
                ],
            )
        )
    return html.Div([
        html.Div(
            style={"display": "flex", "alignItems": "flex-start", "gap": "22px", "marginBottom": "28px"},
            children=[
                html.Div(style={
                    "width": "18px", "height": "18px", "borderRadius": "50%",
                    "backgroundColor": "#FFFFFF", "border": f"4px solid {COULEUR_LIGNE}",
                    "marginTop": "3px", "flexShrink": "0",
                }),
                html.Div(style={"flex": "1"}, children=[
                    html.Div(titre, style={
                        "color": COULEUR_TEXTE_SECONDAIRE, "fontSize": "0.85rem", "letterSpacing": "0.1em",
                        "textTransform": "uppercase", "marginBottom": "8px", "fontWeight": "600",
                    }),
                    html.Div(sous_texte or "", style={
                        "color": COULEUR_TEXTE, "fontSize": "1.15rem", "fontWeight": "700", "marginBottom": "12px",
                    }) if sous_texte else None,
                    html.Div(recit, style={
                        "color": COULEUR_TEXTE, "fontSize": "0.95rem", "lineHeight": "1.6",
                    }) if recit else None,
                ]),
            ],
        ),
        html.Div(lignes, style={"marginLeft": "40px"}),
        html.Div(note or "", style={
            "color": COULEUR_TEXTE_SECONDAIRE, "fontSize": "0.75rem", "marginTop": "16px", "marginLeft": "40px",
        }) if note else None,
    ])


def carte_comparaison_double(titre, items, sous_texte=None, recit=None, note=None,
                              couleur1=CADRE_CORAIL, couleur2=CADRE_CIEL,
                              label1="Partent travailler ailleurs", label2="Viennent travailler ici"):
    """Gabarit a 2 barres par commune (ex: sortants vs entrants), pour comparer 2 valeurs
    sans obliger le lecteur a calculer un ratio ou un ecart lui-meme."""
    valeur_max = max(max(v1, v2) for _, v1, v2 in items)
    lignes = []
    for nom, v1, v2 in items:
        largeur1 = (v1 / valeur_max) * 100
        largeur2 = (v2 / valeur_max) * 100
        lignes.append(
            html.Div(
                style={"marginBottom": "22px"},
                children=[
                    html.Div(nom, style={"color": COULEUR_TEXTE, "fontSize": "1rem", "marginBottom": "8px", "fontWeight": "600"}),
                    html.Div(
                        style={"display": "flex", "justifyContent": "space-between", "fontSize": "0.85rem", "marginBottom": "3px"},
                        children=[
                            html.Span(label1, style={"color": couleur1, "fontWeight": "600"}),
                            html.Span(f"{v1:,.0f}".replace(",", " "), style={"color": COULEUR_TEXTE, "fontWeight": "700"}),
                        ],
                    ),
                    html.Div(
                        style={"backgroundColor": "#E7E5DC", "height": "11px", "width": "100%", "marginBottom": "9px", "borderRadius": "6px", "overflow": "hidden"},
                        children=html.Div(style={"backgroundColor": couleur1, "height": "100%", "width": f"{largeur1}%", "borderRadius": "6px"}),
                    ),
                    html.Div(
                        style={"display": "flex", "justifyContent": "space-between", "fontSize": "0.85rem", "marginBottom": "3px"},
                        children=[
                            html.Span(label2, style={"color": couleur2, "fontWeight": "600"}),
                            html.Span(f"{v2:,.0f}".replace(",", " "), style={"color": COULEUR_TEXTE, "fontWeight": "700"}),
                        ],
                    ),
                    html.Div(
                        style={"backgroundColor": "#E7E5DC", "height": "11px", "width": "100%", "borderRadius": "6px", "overflow": "hidden"},
                        children=html.Div(style={"backgroundColor": couleur2, "height": "100%", "width": f"{largeur2}%", "borderRadius": "6px"}),
                    ),
                ],
            )
        )
    return html.Div([
        html.Div(
            style={"display": "flex", "alignItems": "flex-start", "gap": "22px", "marginBottom": "28px"},
            children=[
                html.Div(style={
                    "width": "18px", "height": "18px", "borderRadius": "50%",
                    "backgroundColor": "#FFFFFF", "border": f"4px solid {COULEUR_LIGNE}",
                    "marginTop": "3px", "flexShrink": "0",
                }),
                html.Div(style={"flex": "1"}, children=[
                    html.Div(titre, style={
                        "color": COULEUR_TEXTE_SECONDAIRE, "fontSize": "0.85rem", "letterSpacing": "0.1em",
                        "textTransform": "uppercase", "marginBottom": "8px", "fontWeight": "600",
                    }),
                    html.Div(sous_texte or "", style={
                        "color": COULEUR_TEXTE, "fontSize": "1.15rem", "fontWeight": "700", "marginBottom": "12px",
                    }) if sous_texte else None,
                    html.Div(recit, style={
                        "color": COULEUR_TEXTE, "fontSize": "0.95rem", "lineHeight": "1.6",
                    }) if recit else None,
                ]),
            ],
        ),
        html.Div(lignes, style={"marginLeft": "40px"}),
        html.Div(note or "", style={
            "color": COULEUR_TEXTE_SECONDAIRE, "fontSize": "0.75rem", "marginTop": "16px", "marginLeft": "40px",
        }) if note else None,
    ])


def carte_point_carte(titre, latitude, longitude, sous_texte, recit=None, note=None):
    carte_html = f"""
    <!DOCTYPE html><html><head><meta charset="utf-8">
    <script src="https://unpkg.com/deck.gl@8.9.28/dist.min.js"></script>
    <style>html,body{{margin:0;padding:0;width:100vw;height:100vh;background:#f5f5f0;}}#map{{position:absolute;top:0;left:0;width:100vw;height:100vh;}}</style>
    </head><body><div id="map"></div><script>
    const {{DeckGL, TileLayer, BitmapLayer, ScatterplotLayer}} = deck;
    new DeckGL({{
      container:"map", mapStyle:null,
      initialViewState:{{longitude:{longitude},latitude:{latitude},zoom:10,pitch:0,bearing:0}},
      controller:true,
      layers:[
        new TileLayer({{
          data:"https://basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}.png",
          minZoom:0,maxZoom:19,tileSize:256,
          renderSubLayers: props => {{
            const {{boundingBox}} = props.tile;
            return new BitmapLayer(props, {{data:null, image:props.data, bounds:[boundingBox[0][0],boundingBox[0][1],boundingBox[1][0],boundingBox[1][1]]}});
          }}
        }}),
        new ScatterplotLayer({{
          data:[{{position:[{longitude},{latitude}]}}],
          getPosition: d => d.position, getFillColor:[79,195,247], getRadius:14, radiusUnits:"pixels",
        }})
      ]
    }});
    </script></body></html>
    """
    return html.Div(
        style={
            "backgroundColor": COULEUR_FOND, "minHeight": "100vh", "display": "flex",
            "flexDirection": "column", "justifyContent": "center", "alignItems": "center",
            "textAlign": "center", "padding": "20px", "boxSizing": "border-box",
            "fontFamily": "'Helvetica Neue', Arial, sans-serif",
        },
        children=[
            html.Div(titre, style={
                "color": COULEUR_TEXTE_SECONDAIRE, "fontSize": "1.3rem", "letterSpacing": "0.15em",
                "textTransform": "uppercase", "marginBottom": "15px",
            }),
            html.Iframe(srcDoc=carte_html, style={"width": "100%", "height": "60vh", "border": "none"}),
            html.Div(sous_texte, style={
                "color": COULEUR_TEXTE, "fontSize": "1.3rem", "marginTop": "20px", "maxWidth": "700px",
            }),
            html.Div(recit, style={
                "color": COULEUR_TEXTE_SECONDAIRE, "fontSize": "1.05rem", "marginTop": "15px",
                "maxWidth": "600px", "lineHeight": "1.6",
            }) if recit else None,
            html.Div(note or "", style={
                "color": COULEUR_TEXTE_SECONDAIRE, "fontSize": "0.8rem", "marginTop": "15px", "fontStyle": "italic",
            }) if note else None,
        ],
    )


def charger_top8(fichier, colonne_nom, colonne_valeur):
    with open(fichier, encoding="utf-8") as f:
        rows = list(pd.read_csv(f).itertuples(index=False))
    return [(getattr(r, colonne_nom), getattr(r, colonne_valeur)) for r in rows[:8]]


def layout_bloc2():
    with open("indicateurs_data.json", encoding="utf-8") as f:
        d = json.load(f)

    top_poles = charger_top8("indicateur_poles_emploi.csv", "nom_commune", "total_travailleurs_entrants")

    solde_df = pd.read_csv("indicateur_solde_travail.csv").sort_values("solde").head(8)
    top_solde_negatif = [(row["nom_commune"], row["sortants"], row["entrants"]) for _, row in solde_df.iterrows()]

    top_autonomie = charger_top8("indicateur_autonomie.csv", "nom_commune", "pct_autonomie")

    top_lignes = charger_top8("indicateur_ligne_chargee.csv", "nom_ligne", "total_flux")

    ticket_total = enveloppe_ticket(
        carte_chiffre(
            id_prefix="total", titre="En Île-de-France",
            valeur_cible=d["total_trajets_reel"],
            format_valeur=lambda v: f"{v:,.0f}".replace(",", " "),
            sous_texte="trajets domicile-travail, chaque jour ouvré",
            note="Source : INSEE, Recensement de la population 2022 (exploitation complémentaire)",
            couleur=CADRE_CORAIL,
        ),
        couleur_bande=CADRE_CORAIL, initiale="T",
    )
    ticket_gini = enveloppe_ticket(
        carte_chiffre(
            id_prefix="gini", titre="Concentration de l'emploi",
            valeur_cible=d["part_emploi_top10pct_communes"],
            format_valeur=lambda v: f"{v:.0f}%",
            sous_texte="de l'emploi francilien se concentre dans seulement 10% des communes",
            recit="L'emploi n'est pas réparti de façon égale sur le territoire. Une poignée de communes concentre l'essentiel de l'activité, quand la grande majorité des communes franciliennes, pourtant bien plus nombreuses, ne pèsent presque rien face à elles.",
            couleur=CADRE_CIEL,
        ),
        couleur_bande=CADRE_CIEL, initiale="C",
    )
    ticket_distance = enveloppe_ticket(
        carte_chiffre(
            id_prefix="distance", titre="Chaque jour, en moyenne",
            valeur_cible=d["distance_moyenne_par_personne_km"],
            format_valeur=lambda v: f"{v:.0f} km",
            sous_texte="parcourus par un actif francilien pour aller travailler et rentrer chez lui",
            couleur=CADRE_JAUNE,
        ),
        couleur_bande=CADRE_JAUNE, initiale="D",
    )
    ticket_poles = enveloppe_ticket(
        carte_classement(
            titre="Les plus grands pôles d'emploi",
            sous_texte="Nombre total de travailleurs venant chaque jour dans la commune",
            recit="Voici les 8 communes qui accueillent chaque jour le plus grand nombre de travailleurs venus d'ailleurs : Paris en tête, suivie par les communes du secteur de La Défense.",
            items=top_poles, couleur=CADRE_LIME,
        ),
        couleur_bande=CADRE_LIME, initiale="E",
    )
    ticket_solde = enveloppe_ticket(
        carte_comparaison_double(
            titre="Là où les habitants partent plus qu'ils n'arrivent",
            sous_texte="Nombre de personnes qui partent travailler ailleurs, contre celles qui viennent travailler ici",
            recit="Asnières-sur-Seine voit chaque jour bien plus d'actifs la quitter pour aller travailler ailleurs que de travailleurs y entrer. Le même déséquilibre touche des arrondissements parisiens comme le 18e et le 20e, pourtant situés à l'intérieur même de la capitale. La proximité avec les grands pôles d'emploi ne suffit donc pas à équilibrer les flux : habiter près de Paris n'implique pas d'y travailler.",
            items=top_solde_negatif,
            couleur1=CADRE_CORAIL, couleur2=CADRE_CIEL,
        ),
        bande_css=f"linear-gradient(90deg, {CADRE_CORAIL} 50%, {CADRE_CIEL} 50%)", initiale="F",
    )
    ticket_autonomie = enveloppe_ticket(
        carte_classement(
            titre="Les communes les plus autonomes",
            sous_texte="Part des actifs qui travaillent dans leur propre commune",
            recit="Dans certaines communes, une bonne partie des habitants travaillent sur place, sans avoir besoin de se déplacer loin. Voici celles où cette indépendance est la plus marquée.",
            items=top_autonomie, unite="%", echelle_max=100,
            note="Communes de moins de 1000 actifs exclues (résultats non significatifs statistiquement) — la barre est calibrée sur une échelle de 0 à 100%",
            couleur=CADRE_JAUNE,
        ),
        couleur_bande=CADRE_JAUNE, initiale="A",
    )
    ticket_ligne = enveloppe_ticket(
        carte_classement(
            titre="Les lignes les plus chargées",
            sous_texte="Volume de trajets domicile-travail pouvant emprunter chaque ligne",
            recit="Certaines lignes de train supportent, à elles seules, une part énorme des déplacements quotidiens de toute la région.",
            items=top_lignes,
            note="Un même trajet peut être compté sur plusieurs lignes proches (méthode par proximité géographique)",
            couleur=CADRE_LIME,
        ),
        couleur_bande=CADRE_LIME, initiale="L",
    )

    return html.Div(
        style={"background": "transparent", "padding": "0 24px 60px", "maxWidth": "1360px", "margin": "0 auto"},
        children=[
            # Les 3 tickets "chiffre seul" groupes ensemble : ils se collent les uns aux autres,
            # jamais un tout seul isole a cote d'un vide
            html.Div(
                style={
                    "display": "grid", "gridTemplateColumns": "repeat(auto-fit, minmax(300px, 1fr))",
                    "gap": "24px", "marginBottom": "24px",
                },
                children=[ticket_total, ticket_gini, ticket_distance],
            ),
            # Les classements/comparaisons, chacun en pleine largeur, empiles
            html.Div(
                style={"display": "flex", "flexDirection": "column", "gap": "24px"},
                children=[ticket_poles, ticket_solde, ticket_autonomie, ticket_ligne],
            ),
        ],
    )


enregistrer_callback_compteur("total", lambda v: f"{v:,.0f}".replace(",", " "))
enregistrer_callback_compteur("gini", lambda v: f"{v:.3f}")
enregistrer_callback_compteur("distance", lambda v: f"{v:,.0f} km".replace(",", " "))


# ============================================================
# NAVIGATION ENTRE LES 2 BLOCS
# ============================================================

def bandeau_signaletique():
    """Bandeau repere, constant sur toute la page : bande bleue carrelee + plaque de nom de station
    blanche par-dessus, esprit signaletique/metro. Purement decoratif, aucun element fonctionnel."""
    return html.Div(
        style={
            "height": "84px",
            "backgroundColor": MUR_BLEU,
            "backgroundImage": (
                "repeating-linear-gradient(90deg, rgba(255,255,255,0.09) 0px, rgba(255,255,255,0.09) 1px, "
                "transparent 1px, transparent 40px), "
                "repeating-linear-gradient(0deg, rgba(255,255,255,0.07) 0px, rgba(255,255,255,0.07) 1px, "
                "transparent 1px, transparent 40px)"
            ),
            "display": "flex", "alignItems": "center", "justifyContent": "center",
        },
        children=html.Div(
            "ÎLE-DE-FRANCE  ·  RÉSEAU DE MOBILITÉ",
            style={
                "backgroundColor": "#FFFFFF",
                "color": MUR_BLEU,
                "border": f"2px solid {COULEUR_LIGNE}",
                "borderRadius": "10px",
                "padding": "10px 28px",
                "fontFamily": FONT_TITRE, "fontWeight": "700",
                "fontSize": "0.85rem", "letterSpacing": "0.25em",
                "boxShadow": "0 4px 0 rgba(20,19,26,0.15)",
            },
        ),
    )


app = Dash(__name__, suppress_callback_exceptions=True)

app.index_string = '''
<!DOCTYPE html>
<html>
<head>
{%metas%}
<title>{%title%}</title>
{%favicon%}
{%css%}
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;500;600;700;900&display=swap" rel="stylesheet">
<style>
  * { box-sizing: border-box; }
  body {
    margin: 0;
    font-family: 'Archivo', 'Helvetica Neue', Arial, sans-serif;
    background:
      url("data:image/svg+xml,%3Csvg%20xmlns%3D%27http%3A//www.w3.org/2000/svg%27%20width%3D%2750%27%20height%3D%2750%27%3E%20%3Cline%20x1%3D%270%27%20y1%3D%270%27%20x2%3D%2750%27%20y2%3D%270%27%20stroke%3D%27rgba%28255%2C255%2C255%2C0.55%29%27%20stroke-width%3D%271%27/%3E%20%3Cline%20x1%3D%270%27%20y1%3D%270%27%20x2%3D%270%27%20y2%3D%2750%27%20stroke%3D%27rgba%28255%2C255%2C255%2C0.55%29%27%20stroke-width%3D%271%27/%3E%20%3Cline%20x1%3D%270%27%20y1%3D%271.5%27%20x2%3D%2750%27%20y2%3D%271.5%27%20stroke%3D%27rgba%280%2C0%2C0%2C0.14%29%27%20stroke-width%3D%271.5%27/%3E%20%3Cline%20x1%3D%271.5%27%20y1%3D%270%27%20x2%3D%271.5%27%20y2%3D%2750%27%20stroke%3D%27rgba%280%2C0%2C0%2C0.14%29%27%20stroke-width%3D%271.5%27/%3E%20%3C/svg%3E") repeat,
      linear-gradient(180deg, #F7F4EC 0%, #F7F4EC 56%, #2F5C8A 56%, #2F5C8A 100%);
    background-attachment: fixed;
  }
  .ticket {
    transition: transform 0.18s ease, box-shadow 0.18s ease;
    box-shadow: 0 4px 0 rgba(20,19,26,0.06), 0 10px 22px rgba(20,19,26,0.10);
  }
  .ticket:hover {
    transform: translateY(-4px);
    box-shadow: 0 6px 0 rgba(20,19,26,0.07), 0 18px 34px rgba(20,19,26,0.16);
  }
  .repere-ligne {
    transition: background-color 0.15s ease;
  }
</style>
</head>
<body>
{%app_entry%}
<footer>
{%config%}
{%scripts%}
{%renderer%}
</footer>
</body>
</html>
'''

# Page unique : bandeau repere, puis la carte en direct, puis l'analyse (defilement continu, pas d'onglets)
app.layout = html.Div([
    bandeau_signaletique(),
    layout_bloc1(),
    layout_bloc2(),
])

server = app.server  # necessaire pour l'hebergement (Render / gunicorn appelle "app:server")


if __name__ == "__main__":
    app.run(debug=True)

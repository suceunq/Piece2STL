# Piece2STL

**Version 0.3.1 — photogrammétrie, IA locale multi-GPU et Meshy Cloud facultatif**

Piece2STL transforme une série de photos ou une courte vidéo d'un objet réel en
maillage 3D calibré, contrôlé et exportable en STL/3MF. Les calculs restent sur
l'ordinateur : FFmpeg prépare la vidéo, COLMAP reconstruit les caméras,
OpenMVS crée le maillage et PyMeshLab le nettoie/répare.

Trois moteurs sont disponibles : photogrammétrie multi-vues, TripoSR local et
Meshy 6 Cloud facultatif. Meshy n'est utilisé que lorsque son choix est confirmé
et avec la clé de l'utilisateur ; les autres modes restent entièrement locaux.

## Utilisation rapide

### Installateur Windows recommandé

Lance `dist/installer/Piece2STL-Setup-0.3.1.exe`. L'assistant moderne installe
l'application sans droits administrateur, crée les raccourcis Bureau et Menu
Démarrer et propose de lancer le logiciel à la fin. La version portable reste
disponible dans `dist/Piece2STL/`.

Au premier lancement, Piece2STL analyse CPU, RAM, GPU, VRAM et pilote. NVIDIA
RTX, AMD RX 6000+ et Intel Arc récents sont accélérés, avec repli CPU universel.

### Version portable

Lance `dist/Piece2STL/Piece2STL.exe`. Python, COLMAP, OpenMVS et FFmpeg sont
inclus dans le dossier portable produit sur la machine de développement.
Pour une installation classique, double-clique sur
`dist/Piece2STL/Installer Piece2STL.bat` : l'application est copiée dans le
profil Windows et des raccourcis Bureau/menu Démarrer sont créés sans droits
administrateur.

### Installation facultative du mode IA

Depuis l'application, clique sur **Installer/configurer l'IA**, ou lance
`Installer IA Piece2STL.bat`. L'installateur détecte automatiquement le GPU :

| Constructeur | Backend privilégié | Repli |
|---|---|---|
| AMD Radeon compatible | PyTorch ROCm | CPU |
| NVIDIA GeForce/Quadro | PyTorch CUDA | CPU |
| Intel Arc/Core Ultra | PyTorch XPU | CPU |
| Autre GPU DirectX | CPU portable | CPU |

Le runtime IA est isolé dans `.ai-venv` avec Python 3.12. L'installation peut
occuper 7 à 10 Go en incluant PyTorch, ROCm/CUDA/XPU et les caches des modèles.
Elle ne modifie pas l'environnement Python de l'application principale.

Depuis la version 0.2.1, l'installation lancée depuis Piece2STL reste dans
l'interface : aucune console PowerShell n'est affichée. Une barre indique le
pourcentage de l'étape globale, un texte explique l'opération en cours et le
journal technique peut être affiché à la demande. La fenêtre peut être réduite
pendant le téléchargement et aucun redémarrage n'est nécessaire à la fin.

### Version de développement

Double-clique sur `Lancer Piece2STL.bat`, ou exécute :

```powershell
.\.venv\Scripts\python.exe scripts\piece2stl_app.py
```

## Parcours utilisateur

1. Choisis **Dossier de photos** ou **Vidéo**.
2. Sélectionne un dossier de destination disposant idéalement de plus de 5 Go.
3. Active éventuellement l'exclusion des images floues.
4. Clique sur **Créer mon modèle 3D**.
5. Inspecte le résultat dans l'aperçu 3D.
6. Si nécessaire, utilise d'abord la réparation prudente, puis intensive.
7. Clique sur **Mettre à l'échelle**, sélectionne deux points et saisis leur
   distance réelle en millimètres.
8. Utilise `export_scaled_mm.stl` pour l'impression.

Pour une génération rapide, choisis **Photo unique — IA locale**, sélectionne
une image avec un sujet isolé et choisis Rapide, Standard ou Détaillé. Le
maillage IA passe ensuite par les mêmes contrôles, réparation, calibration et
exports que la photogrammétrie.

Pour la qualité cloud, choisis **Photo unique — Meshy Cloud**, saisis une clé
depuis le lien officiel intégré et confirme l'envoi. La clé peut être conservée
dans le Gestionnaire d'identifiants Windows. Piece2STL demande Meshy 6, texture
PBR, suppression de l'éclairage et remaillage haute définition, puis produit un
GLB texturé et un STL nettoyé.

Le bouton **Annuler** arrête proprement FFmpeg, COLMAP ou OpenMVS. Le dossier
partiel est conservé pour diagnostic. Un projet peut être rouvert avec
**Reprendre un projet**, sans recommencer la reconstruction.

## Conseils de prise de vue

- Utilise 40 à 100 images nettes avec environ 70 % de recouvrement.
- Fais un tour complet, puis un second tour depuis un angle plus haut.
- Garde la pièce entière dans l'image.
- Utilise un éclairage diffus et constant.
- Place l'objet sur un fond texturé, sans le déplacer entre les photos.
- Matifie temporairement les surfaces brillantes si le matériau le permet.
- Place une cote connue ou mesure une distance facilement identifiable.

Les objets transparents, réfléchissants, très fins ou comportant des cavités
invisibles restent difficiles à reconstruire par photogrammétrie.

## Fichiers d'un projet

| Fichier | Rôle |
|---|---|
| `piece2stl_project.json` | État permettant la reprise du projet |
| `input_quality_report.json` | Images détectées comme floues et sélection finale |
| `mesh_cleaned.ply` | Maillage nettoyé d'origine |
| `mesh_report.json` | Dimensions et contrôles topologiques |
| `mesh_repaired.ply` | Réparation conservée séparément |
| `repair_report.json` | Comparaison avant/après réparation |
| `export_unscaled.stl` | Export sans dimension réelle |
| `export_scaled_mm.stl` | Export final calibré en millimètres |
| `mesh_report_scaled.json` | Contrôle du modèle final |

Un maillage est marqué imprimable lorsque le contrôle confirme son étanchéité,
la cohérence des faces et un volume valide. Cela ne remplace pas la vérification
des tolérances mécaniques ni l'aperçu du logiciel de tranchage.

## Installation de développement

Prérequis : Python 3.11, FFmpeg sur le PATH et les builds CPU de COLMAP/OpenMVS
dans `vendor/`.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m unittest discover -s tests -v
```

## Construction Windows autonome

```powershell
pip install -r requirements-build.txt
powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
powershell -ExecutionPolicy Bypass -File scripts\build_installer.ps1
```

La distribution est créée dans `dist/Piece2STL/`. Elle pèse environ 1,55 Go,
principalement à cause de VTK, COLMAP, OpenMVS et FFmpeg. Le script inclut FFmpeg
s'il est accessible sur le PATH pendant la construction.

## Ligne de commande

```powershell
python scripts\scan_to_stl.py --images photos --workspace projet
python scripts\scan_to_stl.py --video scan.mp4 --workspace projet
```

Le CLI exporte un STL non calibré. La calibration interactive est disponible
avec `scripts/pick_scale.py` ou directement dans l'application.

## Limites de la version 0.3.0

- Le premier lancement IA télécharge et initialise plusieurs modèles ; il est
  sensiblement plus long que les suivants.
- Les GPU AMD non pris en charge par ROCm et les GPU Intel sans XPU utilisent le
  repli CPU, plus lent mais fonctionnel.
- Les zones invisibles d'une image unique sont estimées par l'IA et ne doivent
  jamais être considérées comme une mesure mécanique fiable.
- Une cote connue donne une échelle globale, pas une garantie métrologique.
- Les zones jamais photographiées ne peuvent pas être reconstruites fidèlement.
- La réparation intensive peut fermer une ouverture de manière géométriquement
  plausible mais différente de la pièce réelle : inspecte toujours le résultat.
- Meshy Cloud nécessite un compte, une clé API, une connexion et des crédits ;
  ses conditions et tarifs sont ceux de Meshy.

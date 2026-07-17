# Piece2STL 0.3.0

## Expérience Windows professionnelle

- interface modernisée avec quatre grandes cartes de source ;
- icône Piece2STL personnalisée dans l'application et l'installateur ;
- installateur Inno Setup, raccourcis Bureau/Menu Démarrer et lancement final ;
- diagnostic CPU, RAM, GPU, VRAM et pilote au premier lancement ;
- panneau désactivable GPU/VRAM/température/mémoire pendant les calculs locaux ;
- mise à jour GitHub au démarrage et depuis le menu, téléchargement vérifié SHA-256.

## Qualité 3D et cloud facultatif

- processus enfants totalement invisibles sous Windows ;
- BiRefNet, recadrage haute résolution et TripoSR automatique 256/320/384 ;
- nettoyage des artefacts, lissage Taubin, normales et contrôle d'étanchéité ;
- bascule instantanée aperçu texturé / maillage brut avec arêtes ;
- Meshy 6 Cloud facultatif avec clé masquée, stockage Credential Manager, lien
  officiel, consentement avant envoi, progression, GLB PBR et STL nettoyé ;
- aucune clé API écrite dans les projets ou les journaux.

Validation finale : 27 tests automatisés, détection réelle AMD Radeon RX 9060
XT 15,9 Go, génération locale réelle (101 330 sommets / 202 672 faces,
étanche), trajet Meshy simulé complet, lancement portable et installation / 
lancement / désinstallation dans un dossier isolé.

SHA-256 de `Piece2STL.exe` :

`276E7624A0367A73D6E34B86B0CE923D20E0A3350178A0FB1A6F7104F5264EEE`

SHA-256 de `Piece2STL-Setup-0.3.0.exe` :

`4307477AB35FD91819BF36B048F821190AFFDA9EEC22E16ED565D818ACE24339`

## Version 0.2.1

## Installation IA intégrée

- installation AMD, NVIDIA, Intel ou CPU exécutée en arrière-plan ;
- aucune fenêtre PowerShell ouverte depuis l'application ;
- pourcentage global et explication en français à chaque étape ;
- journal technique repliable, automatiquement affiché en cas d'erreur ;
- annulation avec arrêt de tout l'arbre des processus d'installation ;
- accents compatibles avec Windows PowerShell 5.1 ;
- utilisation de l'IA immédiatement après l'installation, sans redémarrage.

Validation 0.2.1 : 21 tests automatisés réussis, travailleur d'installation
exécuté sur AMD ROCm, marqueurs 2 à 100 % reçus avec succès et nouvel
exécutable démarré depuis la distribution Windows.

SHA-256 de `Piece2STL.exe` :

`16C3E360ADA3E1860142D226FCDA3364D14FA115986FC9E99F3D827E6ECE4F75`

Distribution 0.2.1 : `dist/Piece2STL/` (environ 1,76 Go hors runtime IA).

## Version 0.2.0

## Mode IA local multi-constructeur

- TripoSR intégré pour générer un maillage depuis une seule photo ;
- AMD ROCm, NVIDIA CUDA et Intel XPU sélectionnés automatiquement ;
- repli CPU lorsque l'accélération n'est pas disponible ;
- nouvelle tentative CPU automatique si une opération GPU échoue ou manque de mémoire ;
- extraction marching-cubes portable sans extension CUDA ;
- environnement Python 3.12 séparé et installateur idempotent ;
- choix de qualité 128/192/256 dans l'interface ;
- annulation de tout l'arbre de processus et libération de la VRAM ;
- photos et calculs conservés localement.

Validation AMD : Radeon RX 9060 XT, ROCm 7.2.1, PyTorch 2.9.1. Une génération
réelle a produit 11 084 sommets et 22 164 faces ; le maillage était étanche,
cohérent, volumique et sans arête ouverte.

Le repli CPU a également été exécuté de bout en bout : génération réussie en
156 secondes à la résolution 64, avec 3 782 sommets et 7 560 faces.

- 19 tests automatisés réussis ;
- worker utilisé par l'interface validé sur AMD ;
- worker inclus dans le paquet Windows validé sur AMD ;
- exécutable 0.2.0 démarré avec succès.

SHA-256 de `Piece2STL.exe` :

`061A505A7312B77B311F4E19D014B7E9103C46A3ABAECA38BF50661EC332C12A`

Distribution 0.2.0 : `dist/Piece2STL/` (1 764 819 250 octets hors runtime IA).

## Version 0.1.0

Première version MVP Windows utilisable sans terminal.

## Fonctions livrées

- import d'un dossier de photos ou d'une vidéo ;
- extraction FFmpeg et contrôle du flou ;
- reconstruction CPU COLMAP + OpenMVS ;
- progression détaillée et annulation propre ;
- nettoyage, diagnostic et réparation prudente/intensive ;
- aperçu 3D intégré ;
- calibration par deux points et export STL/3MF en millimètres ;
- sauvegarde et reprise des projets ;
- import de maillages PLY, STL, OBJ, 3MF et GLB ;
- distribution Windows autonome et installateur utilisateur.

## Validation de la livraison

- 17 tests automatisés réussis ;
- reconstruction complète réussie sur 48 images synthétiques ;
- maillage final réparé de 3 à 0 arête ouverte ;
- résultat final étanche, cohérent et volumique ;
- exécutable portable démarré avec succès ;
- COLMAP 4.1.0, OpenMVS et FFmpeg 8.1.2 présents dans le paquet.

Distribution : `dist/Piece2STL/` (1 624 727 028 octets).

SHA-256 de `Piece2STL.exe` :

`25E9F8F6B3F884618298C2E1D467A66CED902F2A87049BEC92A1CE7503C23329`

## Limite historique de la 0.1.0

Le mode IA mono-image n'est pas inclus dans cette version : la machine de
développement ne possède pas de GPU NVIDIA et aucun modèle 3D local compatible
n'y est installé. Cette décision évite de livrer un bouton lent ou non
fonctionnel. Le moteur de précision local constitue le produit 0.1.0 ; un futur
backend IA devra rester optionnel et ne devra jamais être présenté comme une
mesure fiable d'une pièce mécanique.

Cette limite est levée par le backend multi-constructeur de la version 0.2.0.

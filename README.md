# Elden Death Counter

Compteur de morts automatique pour Elden Ring, à afficher en direct dans OBS
ou Streamlabs. Deux compteurs à l'écran : le total depuis le début, et le
nombre de morts sur le boss en cours, que tu remets à zéro d'une touche quand
tu le bats.

La détection lit le texte affiché à l'écran. Aucune lecture mémoire, aucun
hook dans le processus du jeu : rien qui puisse intéresser l'anti-triche.

## Installation

**Sans Python.** Télécharge `elden-counter.exe` dans les
[Releases](../../releases).

**Avec Python 3.10 ou plus récent :**

```
pip install elden-death-counter
```

Il faut aussi le moteur Tesseract, avec les données de ta langue de jeu.
Windows : l'installeur de [UB-Mannheim](https://github.com/UB-Mannheim/tesseract/wiki),
en cochant la langue voulue. Linux : `apt install tesseract-ocr tesseract-ocr-fra`.

## Prise en main

```
elden-counter setup
elden-counter run --boss "Malenia"
```

Le setup te demande de mourir une fois et d'appuyer sur F8 pendant que le
texte est affiché. Il repère tout seul la ligne de texte, ouvre une page dans
ton navigateur pour que tu confirmes le cadre d'un clic, puis lit le texte et
le mémorise. C'est tout ce dont il a besoin.

Si ton jeu n'est pas en français, précise la langue : `--lang eng`,
`--lang deu`, `--lang jpn`. L'outil ne connaît aucun texte à l'avance, il
apprend le tien.

Ajoute ensuite dans OBS une **source navigateur** sur `http://127.0.0.1:4747`,
en 600×300. Le fond est transparent.

## Raccourcis pendant le stream

| Touche | Effet |
|---|---|
| F9 | Ajouter une mort aux deux compteurs |
| F10 | En retirer une |
| F11 | Remettre le compteur du boss à zéro, le total reste intact |
| F12 | Boss vaincu : le score part dans l'historique et le compteur repart de zéro |

## Autres commandes

```
elden-counter diagnose         # voir ce que lit le détecteur, en direct
elden-counter boss "Radagon"   # changer le boss affiché
elden-counter history          # revoir tes scores sur les boss battus
elden-counter reset            # remettre le boss à zéro
elden-counter reset --all      # tout effacer, historique compris
elden-counter run --manual     # comptage aux raccourcis uniquement
```

## Pourquoi la lecture de texte

La première version corrélait la forme d'une empreinte apprise sur plusieurs
morts. Ça marchait, mais elle ne comprenait pas ce qu'elle regardait : le bord
du voile sombre, ou la boîte de dialogue de la carte, lui ressemblaient assez
pour la déclencher. Il a fallu empiler les garde-fous — constance entre morts,
exclusion de l'interface, filtrage par forme, contre-exemples, signatures
multiples — et il restait des angles morts.

Lire le texte est spécifique au sens. Un assombrissement ne lit rien, la carte
lit autre chose. Sur les mêmes captures réelles qui mettaient la corrélation en
échec : 7 morts sur 12 lues, **zéro faux positif sur 37 images**, menus et
carte compris. La pire vraie lecture est à 0,85 de similitude, la pire fausse
à 0,40.

Les morts non lues sont des images dégradées — fondu, texte délavé sur une
scène très claire. En fonctionnement, l'écran est analysé deux fois par
seconde pendant les quelques secondes d'affichage : il suffit qu'une seule
lecture passe.

## Réglages

`--similarity` ajuste le seuil de ressemblance, 0,60 par défaut. Monte-le si
un autre écran déclenche à tort, descends-le si des morts passent à travers.

`elden-counter diagnose` affiche en direct ce qui est lu, ligne par ligne.
C'est le premier endroit où regarder quand quelque chose cloche.

Sur un écran secondaire, précise `--monitor 2`.

## Ce qui peut poser problème

Sous Windows, les raccourcis clavier globaux demandent souvent de lancer le
terminal en administrateur.

Sur console via carte d'acquisition, fais le setup avec la fenêtre de preview
dans la position exacte où elle restera pendant le stream.

## Licence

MIT.

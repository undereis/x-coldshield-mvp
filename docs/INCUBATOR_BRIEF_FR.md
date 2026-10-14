# X ColdShield — note de présentation pour l’incubation

**Stade :** MVP 0.2, prototype de laboratoire local. **Responsable du projet :** mainteneur du dépôt. **Objectif :** évaluation technique et découverte client ; ce document ne constitue pas une preuve de déploiement industriel.

## Problème et hypothèse client

X ColdShield étudie le filtrage de commandes de réfrigération lorsqu’un message industriel valide demande une opération hors d’une enveloppe de fonctionnement convenue. L’hypothèse initiale est qu’une passerelle capable d’expliquer l’acceptation ou le refus d’une écriture pourrait intéresser des intégrateurs frigorifiques, des opérateurs de chaîne du froid et des distributeurs alimentaires.

Le besoin client, le processus d’achat et la disposition à payer restent à valider. Aucune taille de marché chiffrée ni traction commerciale n’est revendiquée.

## Approche technique

Le prototype associe validation du protocole et politique de commandes adaptée au cas d’usage. Une passerelle Modbus TCP locale autorise un ensemble limité de fonctions et de registres de laboratoire. Elle contrôle les consignes de température signées, l’autorisation temporaire de maintenance et la coordination du dégivrage avant de transmettre une opération autorisée à un simulateur logiciel. Un tableau de bord présente les consignes simulées et les décisions enregistrées.

La différenciation recherchée est une politique explicable fondée sur la sémantique des commandes frigorifiques. Son efficacité par rapport aux solutions existantes reste à évaluer. Les règles actuelles sont des contraintes définies manuellement, pas un modèle thermodynamique validé ni un système de détection adaptatif.

## Architecture et preuves

La démonstration utilise uniquement l’interface locale : un client ou le tableau de bord Streamlit envoie une requête à la passerelle sur le port 5021, qui l’évalue et communique avec le simulateur sur le port 5020. La configuration est validée, la maintenance est fermée par défaut et les événements d’intention et de résultat sont stockés dans une base SQLite locale. Des réservations persistantes de dégivrage permettent un traitement conservateur après une issue de communication ambiguë.

Le dossier de preuves comprend le [README](../README.md), l’[architecture](../ARCHITECTURE.md), les [limites de sécurité](../SECURITY.md), l’[audit de la version initiale](../AUDIT_REPORT.md), le [rapport de tests](../TEST_REPORT.md) et le [guide de démonstration](DEMO.md). Seules les vérifications réellement exécutées et consignées dans le rapport constituent des résultats ; la présence de code ou d’un scénario prévu ne prouve pas sa réussite.

## Limites actuelles

Le simulateur est illustratif ; il ne constitue pas une implémentation validée d’un contrôleur Danfoss, Carel ou d’un autre constructeur. La compatibilité industrielle, BACnet, le déploiement matériel, l’audit de sécurité indépendant et la validation sur site ne sont pas démontrés. Les valeurs affichées sont des consignes commandées, pas des mesures de capteurs. La fenêtre de maintenance est un mécanisme local sans vérification d’identité des intervenants. Les enregistrements locaux sont modifiables par un administrateur de la machine et ne sont pas immuables. Aucune certification NIS 2 ni conclusion de conformité n’est revendiquée.

## Prochains jalons

Les priorités sont le fuzzing de l’analyseur de protocole, les essais de panne et de reprise, les mesures reproductibles de performance et une revue par des spécialistes du froid et de la cybersécurité OT. Viendront ensuite l’administration authentifiée, les profils de registres propres à chaque contrôleur et une revue de sécurité indépendante. Un pilote avec un partenaire dépendrait d’un plan de sécurité et d’autorisation distinct. La [feuille de route](../ROADMAP.md) précise les preuves attendues à chaque étape.

## Plan proposé avec des partenaires français

Aucun partenariat ni pilote n’est établi par les travaux de ce dépôt. La démarche proposée serait :

1. Obtenir des mises en relation avec un intégrateur frigorifique français, un spécialiste de sécurité OT et un opérateur de chaîne du froid pour des entretiens exploratoires.
2. Définir ensemble les registres, le processus de maintenance, les risques et les critères d’acceptation à partir de documentation constructeur et de traces synthétiques.
3. Reproduire les exigences dans un simulateur isolé, puis faire examiner les décisions et les cas de panne par les ingénieurs des partenaires.
4. Envisager un banc d’essai isolé uniquement après autorisation explicite, revue de sécurité et plan de retour arrière. Ne pas connecter ce MVP à des équipements frigorifiques en exploitation pendant la démonstration actuelle.

EuraTechnologies représente une cible d’incubation possible : son site officiel mentionne la cybersécurité et l’industrie parmi ses domaines d’activité. Il s’agit d’une hypothèse d’adéquation, pas d’une affiliation ni d’un soutien acquis. Voir [EuraTechnologies](https://www.euratechnologies.com/en), consulté le 14 octobre 2026. Les conditions et l’ouverture des candidatures doivent être vérifiées séparément avant tout dépôt.

L’accompagnement recherché porterait sur la confrontation technique, la découverte client, les mises en relation et la définition d’un plan de commercialisation crédible. La question immédiate est de déterminer si les preuves de laboratoire et le programme de validation proposé justifient de poursuivre l’étude.

Installe l'agent Alloy sur ce module pour qu'il pousse ses logs Docker +                                                      
  journald vers la stack centralisée Loki+Grafana hébergée sur LXC 116                                                          
  (`agflow-logs`). Cette stack agrège les logs de toute la suite agflow et                                                    
  expose Grafana sur https://log.yoops.org (auth Keycloak SSO).                                                                 
                                                                                    
  Spec :                                                                                                                        
                                                                                                                                
  1. Crée un dossier `infra/alloy-agent/` à la racine du repo, contenant :                                                      
                                                                                                                                
     a) `docker-compose.yml` :                                                                                                  
        services:                                                                                                               
          alloy:
            image: grafana/alloy:v1.5.1
            container_name: agflow-alloy-agent
            restart: unless-stopped
            command:
              - run
              - /etc/alloy/config.alloy
              - --storage.path=/var/lib/alloy/data
              - --server.http.listen-addr=0.0.0.0:12345
            environment:
              LOKI_URL: ${LOKI_URL:?LOKI_URL is required}
              HOSTNAME: ${HOSTNAME:?HOSTNAME is required}
            volumes:
              - ./config.alloy:/etc/alloy/config.alloy:ro
              - /var/run/docker.sock:/var/run/docker.sock:ro
              - /var/log:/var/log:ro
              - /run/log/journal:/run/log/journal:ro
              - /etc/machine-id:/etc/machine-id:ro
              - alloy_data:/var/lib/alloy/data
        volumes:
          alloy_data:

     b) `config.alloy` — collecteur Docker socket + journald avec :
        - Source 1 : `discovery.docker` qui lit /var/run/docker.sock,
          relabel pour extraire `container`, `compose_service`,
          `compose_project`
        - Source 2 : `loki.source.journal` qui lit /run/log/journal avec
          labels `unit`, `host`
        - Sortie : `loki.write` vers env `LOKI_URL`, label commun
          `host = env("HOSTNAME")` et `module = "<NOM_DU_MODULE>"`
          (exemple "security", "workflow", "chat" — adapte selon le module
          que tu gères)
        - logging level "info", format "logfmt"

     c) `config-journald-only.alloy` — variante sans Docker (pour les LXC
        sans Docker installé), juste la Source 2 + loki.write.

     d) `.env.template` :
        LOKI_URL=http://192.168.10.<IP_LXC116>:3100/loki/api/v1/push
        HOSTNAME=lxc<CTID>

  2. Crée `scripts/infra/deploy-alloy.sh` qui :
     - prend en argument un CTID Proxmox (ou un alias SSH)
     - rsync `infra/alloy-agent/` vers la machine cible (`/opt/alloy/`)
     - vérifie qu'un `.env` existe sinon copie depuis `.env.template`
       en demandant de l'éditer
     - lance `docker compose up -d` côté cible
     - smoke : curl http://<host>:12345/-/ready côté Alloy puis vérifie
       `docker logs agflow-alloy-agent --tail 20`

  3. Documente dans `infra/alloy-agent/README.md` :
     - rappel : la stack Loki centrale tourne sur LXC 116 (agflow-logs)
       et expose http://<IP_LXC116>:3100/loki/api/v1/push pour les pushes
       entrants
     - Grafana est sur https://log.yoops.org (auth Keycloak realm yoops,
       client `grafana`, roles admin|editor|viewer)
     - Pour ajouter un nouveau host à la collecte : déployer ce dossier
       puis vérifier dans Grafana dashboard "Docker" qu'il apparaît dans
       le label `host`

  4. Si le module a des stacks Docker Swarm (pas seulement docker
     compose), Alloy collecte aussi automatiquement les logs des
     services Swarm via le Docker socket — pas de config supplémentaire.

  5. NE TOUCHE PAS au Loki/Grafana central côté LXC 116 — c'est un
     service partagé, l'ops gère ce repo séparément (infra/logs-stack/).
     Ton job ici est uniquement le COLLECTEUR (Alloy).

  Référence d'implémentation déjà mergée dans agflow.docker :
  https://github.com/gaelgael5/agflow.docker, dossier `infra/alloy-agent/`
  sur la branch `main`.

  À adapter au layout de ton repo si différent (ex. `ops/alloy/` au lieu
  de `infra/alloy-agent/`), mais garde la structure (compose + config
  alloy + .env.template + script de déploiement).

{
  "args": [
    {
      "arg": "LXC_ID",
      "label_fr": "Identifiant LXC (CT ID)",
      "label_en": "LXC ID (CT ID)",
      "description_fr": "Numéro unique du container Proxmox (ex: 200, 201…)",
      "description_en": "Unique Proxmox container ID (e.g. 200, 201…)",
      "type": "integer",
      "required": true,
      "default": 301,
      "min": 100,
      "max": 999
    },
    {
      "arg": "LXC_NAME",
      "label_fr": "Nom du container",
      "label_en": "Container hostname",
      "description_fr": "Hostname DNS (lettres, chiffres, tirets — ex: agflow-test-01)",
      "description_en": "DNS hostname (letters, digits, dashes — e.g. agflow-test-01)",
      "type": "string",
      "required": true,
      "default": "ag-swarm-1",
      "pattern": "^[a-zA-Z0-9-]+$"
    },
    {
      "arg": "MODE",
      "label_fr": "Mode de configuration",
      "label_en": "Configuration mode",
      "description_fr": "Choix du mode du LXC. 'bare' = LXC nu. 'docker' = LXC + Docker. 'swarm' = LXC swarm-ready (modules kernel + /dev/net/tun, sans Docker). 'init-swarm' = LXC + Docker + initialise un nouveau cluster Swarm. 'join-swarm' = LXC + Docker + rejoint un cluster existant (renseigner MANAGER_IP et JOIN_TOKEN).",
      "description_en": "LXC mode selection. 'bare' = bare LXC. 'docker' = LXC + Docker. 'swarm' = swarm-ready LXC (no Docker). 'init-swarm' = LXC + Docker + init new Swarm cluster. 'join-swarm' = LXC + Docker + join existing cluster (set MANAGER_IP and JOIN_TOKEN).",
      "type": "select",
      "required": true,
      "default": "init-swarm",
      "options": [
        { "value": "bare",       "label": "LXC nu (sans Docker, sans Swarm)" },
        { "value": "docker",     "label": "LXC + Docker" },
        { "value": "swarm",      "label": "LXC swarm-ready (sans Docker)" },
        { "value": "init-swarm", "label": "LXC + Docker + init nouveau cluster Swarm" },
        { "value": "join-swarm", "label": "LXC + Docker + rejoindre cluster Swarm existant" }
      ]
    },
    {
      "arg": "STORAGE",
      "label_fr": "Storage Proxmox",
      "label_en": "Proxmox storage",
      "description_fr": "Nom du pool storage pour le rootfs. 'auto' sélectionne automatiquement celui avec le plus d'espace libre.",
      "description_en": "Proxmox storage pool for the rootfs. 'auto' picks the one with most free space.",
      "type": "string",
      "required": false,
      "default": "auto"
    },
    {
      "arg": "DISK_SIZE",
      "label_fr": "Taille du disque (GB)",
      "label_en": "Disk size (GB)",
      "description_fr": "Taille du rootfs en GigaBytes",
      "description_en": "Rootfs size in GigaBytes",
      "type": "integer",
      "required": false,
      "default": 30,
      "min": 10,
      "max": 1000
    },
    {
      "arg": "CORES",
      "label_fr": "Nombre de cœurs CPU",
      "label_en": "CPU cores",
      "description_fr": "Nombre de cœurs alloués au container",
      "description_en": "Number of CPU cores allocated to the container",
      "type": "integer",
      "required": false,
      "default": 4,
      "min": 1,
      "max": 64
    },
    {
      "arg": "MEMORY",
      "label_fr": "RAM (MB)",
      "label_en": "RAM (MB)",
      "description_fr": "Mémoire vive allouée en MégaBytes",
      "description_en": "Memory allocated in MegaBytes",
      "type": "integer",
      "required": false,
      "default": 8192,
      "min": 512,
      "max": 524288
    },
    {
      "arg": "SWAP",
      "label_fr": "Swap (MB)",
      "label_en": "Swap (MB)",
      "description_fr": "Swap alloué en MégaBytes",
      "description_en": "Swap allocated in MegaBytes",
      "type": "integer",
      "required": false,
      "default": 1024,
      "min": 0,
      "max": 524288
    },
    {
      "arg": "BRIDGE",
      "label_fr": "Bridge réseau",
      "label_en": "Network bridge",
      "description_fr": "Nom du bridge Proxmox utilisé par eth0",
      "description_en": "Proxmox bridge name used by eth0",
      "type": "string",
      "required": false,
      "default": "vmbr0"
    },
    {
      "arg": "MANAGER_IP",
      "label_fr": "IP du manager Swarm",
      "label_en": "Swarm manager IP",
      "description_fr": "Uniquement si MODE=join-swarm. IP d'un manager Swarm existant (sans port).",
      "description_en": "Only if MODE=join-swarm. IP of an existing Swarm manager (no port).",
      "type": "string",
      "required": false,
      "default": ""
    },
    {
      "arg": "JOIN_TOKEN",
      "label_fr": "Token de join Swarm",
      "label_en": "Swarm join token",
      "description_fr": "Uniquement si MODE=join-swarm. Token worker ou manager du cluster existant. Récupérable via : pct exec <MANAGER_CTID> -- docker swarm join-token worker -q",
      "description_en": "Only if MODE=join-swarm. Worker or manager token from the existing cluster. Get it via: pct exec <MANAGER_CTID> -- docker swarm join-token worker -q",
      "type": "string",
      "required": false,
      "default": ""
    },
    {
      "arg": "JOIN_AS_MANAGER",
      "label_fr": "Rejoindre comme manager",
      "label_en": "Join as manager",
      "description_fr": "Uniquement si MODE=join-swarm. Si true, le node rejoint comme manager (HA). Sinon comme worker.",
      "description_en": "Only if MODE=join-swarm. If true, node joins as manager (HA). Otherwise as worker.",
      "type": "boolean",
      "required": false,
      "default": false
    },
    {
      "arg": "POOL_OVERLAY",
      "label_fr": "Pool overlay Swarm (CIDR)",
      "label_en": "Swarm overlay pool (CIDR)",
      "description_fr": "Uniquement pour MODE=init-swarm. Pool d'IPs des overlay networks. Choisir un subnet qui ne chevauche pas le LAN.",
      "description_en": "Only for MODE=init-swarm. IP pool for overlay networks. Pick a subnet that does not overlap the LAN.",
      "type": "string",
      "required": false,
      "default": "10.20.0.0/16"
    },
    {
      "arg": "NODE_LABELS",
      "label_fr": "Labels du node Swarm",
      "label_en": "Swarm node labels",
      "description_fr": "Uniquement pour MODE=init-swarm. Labels appliqués au manager initial, format clé=valeur séparé par virgule.",
      "description_en": "Only for MODE=init-swarm. Labels applied to the initial manager, comma-separated key=value pairs.",
      "type": "string",
      "required": false,
      "default": "role=control,tenant=agflow"
    }
  ],
  "command": "mkdir -p /root/lxc && cd /root/lxc && curl -fsSL -o create-lxc.sh https://raw.githubusercontent.com/Configurations/Proxmox/main/LXC/create-lxc.sh && chmod +x create-lxc.sh && FLAGS=''; case '{MODE}' in docker) FLAGS='--docker' ;; swarm) FLAGS='--swarm' ;; init-swarm) FLAGS='--init-swarm' ;; join-swarm) FLAGS='--join-swarm --manager-ip {MANAGER_IP} --token {JOIN_TOKEN}' ;; esac; [ '{JOIN_AS_MANAGER}' = 'true' ] && FLAGS=\"$FLAGS --as-manager\"; STORAGE='{STORAGE}' DISK_SIZE={DISK_SIZE} CORES={CORES} MEMORY={MEMORY} SWAP={SWAP} BRIDGE='{BRIDGE}' POOL_OVERLAY='{POOL_OVERLAY}' NODE_LABELS='{NODE_LABELS}' ./create-lxc.sh {LXC_ID} '{LXC_NAME}' $FLAGS",
  "tags": ["add_node", "create_lxc"]
}
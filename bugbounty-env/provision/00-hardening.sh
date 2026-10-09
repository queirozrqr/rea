#!/usr/bin/env bash
# Fase 0 – sistema base e hardening (Debian 13, executar como root via sudo).
#
# Variáveis opcionais:
#   BB_SSH_ALLOW_FROM="203.0.113.10/32"  restringe o SSH a um IP/CIDR no firewall
#   BB_ASSUME_YES=1                      não pergunta (use só em automação revisada)
source "$(dirname "$0")/../lib/common.sh"

require_root
require_debian

ADMIN_USER="${SUDO_USER:-root}"
ADMIN_HOME="$(getent passwd "${ADMIN_USER}" | cut -d: -f6)"
ADMIN_KEYS="${ADMIN_HOME}/.ssh/authorized_keys"
SSH_RULE="${BB_SSH_ALLOW_FROM:-any}"

# Pré-condições anti-lockout, verificadas antes de qualquer alteração.
if [[ "${ADMIN_USER}" == "root" ]]; then
  die "rode via 'sudo' a partir de um usuário admin com chave SSH; o login de root será bloqueado."
fi
[[ -s "${ADMIN_KEYS}" ]] || die "nenhuma chave em ${ADMIN_KEYS}; configure sua chave SSH antes (ssh-copy-id)."

confirm_plan "hardening do sistema" \
  "apt full-upgrade + pacotes base (ufw, fail2ban, unattended-upgrades, curl, gnupg, xz, unzip)" \
  "criar usuário '${BB_USER}' SEM sudo e copiar as chaves SSH de '${ADMIN_USER}'" \
  "SSH: só chave pública, sem root, AllowUsers ${ADMIN_USER} ${BB_USER}" \
  "firewall: nega toda entrada; libera 22/tcp de '${SSH_RULE}'" \
  "fail2ban (sshd), atualizações de segurança automáticas, sysctl endurecido"

# 1. Pacotes ------------------------------------------------------------------
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get -y full-upgrade
apt-get -y install --no-install-recommends \
  ca-certificates curl gnupg xz-utils unzip git sudo \
  ufw fail2ban unattended-upgrades apt-listchanges \
  util-linux procps

# 2. Usuário de trabalho --------------------------------------------------------
if ! id "${BB_USER}" &>/dev/null; then
  adduser --disabled-password --gecos "" "${BB_USER}"
  log "usuário ${BB_USER} criado (sem senha, sem sudo)."
fi
if id -nG "${BB_USER}" | grep -qw sudo; then
  warn "${BB_USER} está no grupo sudo; removendo (princípio do menor privilégio)."
  gpasswd -d "${BB_USER}" sudo
fi

install -d -m 700 -o "${BB_USER}" -g "${BB_USER}" "/home/${BB_USER}/.ssh"
if [[ ! -s "/home/${BB_USER}/.ssh/authorized_keys" ]]; then
  install -m 600 -o "${BB_USER}" -g "${BB_USER}" "${ADMIN_KEYS}" "/home/${BB_USER}/.ssh/authorized_keys"
fi

# 3. SSH ------------------------------------------------------------------------
ALLOW_USERS="${ADMIN_USER} ${BB_USER}"
sed "s/__BB_ALLOW_USERS__/${ALLOW_USERS}/" "${BB_ROOT}/config/sshd/99-bb-hardening.conf" \
  > /etc/ssh/sshd_config.d/99-bb-hardening.conf
chmod 644 /etc/ssh/sshd_config.d/99-bb-hardening.conf
sshd -t || die "configuração SSH inválida; arquivo NÃO aplicado (remova /etc/ssh/sshd_config.d/99-bb-hardening.conf)."
systemctl reload ssh
warn "teste AGORA, em outro terminal, 'ssh ${ADMIN_USER}@host' e 'ssh ${BB_USER}@host' antes de fechar esta sessão."

# 4. Firewall -------------------------------------------------------------------
ufw --force reset >/dev/null
ufw default deny incoming
ufw default allow outgoing
if [[ "${SSH_RULE}" == "any" ]]; then
  ufw limit 22/tcp comment 'ssh'
else
  ufw limit from "${SSH_RULE}" to any port 22 proto tcp comment 'ssh'
fi
ufw --force enable

# 5. fail2ban, atualizações e sysctl -------------------------------------------
install -m 644 "${BB_ROOT}/config/fail2ban/jail.local" /etc/fail2ban/jail.d/bb-sshd.local
systemctl enable --now fail2ban
systemctl restart fail2ban

echo 'unattended-upgrades unattended-upgrades/enable_auto_updates boolean true' | debconf-set-selections
dpkg-reconfigure -f noninteractive unattended-upgrades

install -m 644 "${BB_ROOT}/config/sysctl/99-bb-hardening.conf" /etc/sysctl.d/99-bb-hardening.conf
sysctl --system >/dev/null

log "fase 0 concluída. Tire o snapshot 'base-limpa' no painel do provedor."

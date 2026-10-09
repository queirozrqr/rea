#!/usr/bin/env bash
# Fase 1 – Node.js (tarball oficial verificado) + rea-agents em versão exata.
# Executar como root (sudo). Ferramentas ficam em /opt/bb-tools (root:root),
# portanto o usuário de trabalho não consegue adulterá-las.
source "$(dirname "$0")/../lib/common.sh"

require_root
require_debian

NODE_DIR="${BB_TOOLS_DIR}/node-v${NODE_VERSION}"
NPM_PREFIX="${BB_TOOLS_DIR}/npm-global"

confirm_plan "Node.js ${NODE_VERSION} + rea-agents@${REA_VERSION}" \
  "baixar ${NODE_TARBALL} de nodejs.org e conferir com SHASUMS256.txt (assinatura GPG: ${BB_NODE_GPG_VERIFY})" \
  "extrair em ${NODE_DIR} e criar links em /usr/local/bin (node, npm, npx)" \
  "npm install -g rea-agents@${REA_VERSION} --ignore-scripts em ${NPM_PREFIX}" \
  "link /usr/local/bin/rea"

install -d -m 755 "${BB_TOOLS_DIR}"
WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT

# 1. SHASUMS + GPG --------------------------------------------------------------
curl --proto '=https' --tlsv1.2 -fsSL -o "${WORK}/SHASUMS256.txt"     "${NODE_DIST_BASE}/SHASUMS256.txt"
if [[ "${BB_NODE_GPG_VERIFY}" == "1" ]]; then
  curl --proto '=https' --tlsv1.2 -fsSL -o "${WORK}/SHASUMS256.txt.sig" "${NODE_DIST_BASE}/SHASUMS256.txt.sig"
  # Chaveiro oficial dos releasers do Node.js (repositório nodejs/release-keys).
  curl --proto '=https' --tlsv1.2 -fsSL -o "${WORK}/pubring.kbx" \
    "https://github.com/nodejs/release-keys/raw/HEAD/gpg/pubring.kbx"
  gpgv --keyring "${WORK}/pubring.kbx" "${WORK}/SHASUMS256.txt.sig" "${WORK}/SHASUMS256.txt" \
    || die "assinatura GPG de SHASUMS256.txt inválida."
  log "assinatura GPG de SHASUMS256.txt válida."
fi
NODE_SHA="$(awk -v f="${NODE_TARBALL}" '$2==f {print $1}' "${WORK}/SHASUMS256.txt")"
[[ -n "${NODE_SHA}" ]] || die "${NODE_TARBALL} não consta em SHASUMS256.txt."

# 2. Node -----------------------------------------------------------------------
if [[ ! -x "${NODE_DIR}/bin/node" ]]; then
  fetch_verified "${NODE_DIST_BASE}/${NODE_TARBALL}" "${NODE_SHA}" "${WORK}/${NODE_TARBALL}"
  install -d -m 755 "${NODE_DIR}"
  tar -xJf "${WORK}/${NODE_TARBALL}" -C "${NODE_DIR}" --strip-components=1 --no-same-owner
fi
for bin in node npm npx; do
  ln -sfn "${NODE_DIR}/bin/${bin}" "/usr/local/bin/${bin}"
done
[[ "$(node -v)" == "v${NODE_VERSION}" ]] || die "node -v inesperado: $(node -v)"

# 3. REA --------------------------------------------------------------------------
# --ignore-scripts: nenhum script de ciclo de vida de dependência roda como root.
install -d -m 755 "${NPM_PREFIX}"
npm install --global --prefix "${NPM_PREFIX}" --ignore-scripts --no-fund --no-audit \
  "rea-agents@${REA_VERSION}"
ln -sfn "${NPM_PREFIX}/bin/rea" /usr/local/bin/rea
chmod -R go-w "${BB_TOOLS_DIR}"

log "versão instalada: $(rea --version 2>/dev/null || echo '?')"
log "fase 1 concluída. Próximo: provision/20-providers.sh"

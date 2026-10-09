#!/usr/bin/env bash
# Fase 2 – provedores do REA (executar como root via sudo).
#
# Uso:
#   sudo ./20-providers.sh                 # todos os componentes
#   sudo ./20-providers.sh web android     # só os escolhidos
#
# Componentes: web android capture native elf crash firmware jsrecovery
# Componentes cujo URL/SHA-256 ainda está vazio em versions.env são PULADOS
# (modo "todos") ou ABORTAM (quando pedidos explicitamente).
source "$(dirname "$0")/../lib/common.sh"

require_root
require_debian

ALL=(web android capture native elf crash firmware jsrecovery)
if [[ $# -eq 0 ]]; then
  SELECTED=("${ALL[@]}"); EXPLICIT=0
else
  SELECTED=("$@"); EXPLICIT=1
fi
for c in "${SELECTED[@]}"; do
  [[ " ${ALL[*]} " == *" ${c} "* ]] || die "componente desconhecido: ${c} (válidos: ${ALL[*]})"
done

SKIPPED=()
# Pula (modo todos) ou aborta (modo explícito) quando falta URL/hash.
needs() {
  local comp="$1"; shift
  local v
  for v in "$@"; do
    if [[ -z "${!v:-}" ]]; then
      if [[ ${EXPLICIT} -eq 1 ]]; then
        die "${comp}: ${v} vazio em versions.env (veja README, 'Como obter os hashes')."
      fi
      warn "${comp}: ${v} vazio; componente pulado."
      SKIPPED+=("${comp} (${v})")
      return 1
    fi
  done
}

confirm_plan "provedores: ${SELECTED[*]}" \
  "web: chromium + xvfb/x11vnc (somente loopback)" \
  "android: OpenJDK 21 + jadx-headless-mcp ${JADX_MCP_VERSION} (SHA-256 fixo)" \
  "capture: mitmproxy==${MITMPROXY_VERSION} em venv isolado" \
  "native: Ghidra ${GHIDRA_VERSION} (zip + SHA-256 de versions.env)" \
  "elf: pwntools==${PWNTOOLS_VERSION} pyelftools==${PYELFTOOLS_VERSION} unicorn==${UNICORN_VERSION} em venv" \
  "crash: gdb (apt) + pwndbg ${PWNDBG_VERSION} (tarball + SHA-256)" \
  "firmware: binwalk ${BINWALK_VERSION} (cargo --locked) + unblob==${UNBLOB_VERSION} (venv) + extratores" \
  "jsrecovery: wakaru ${WAKARU_VERSION} (binário + SHA-256)"

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get -y install --no-install-recommends python3 python3-venv python3-pip util-linux

install_web() {
  apt-get -y install --no-install-recommends \
    chromium chromium-sandbox fonts-liberation fonts-noto-color-emoji \
    xvfb x11vnc openbox
}

install_android() {
  apt-get -y install --no-install-recommends openjdk-21-jdk-headless
  fetch_verified "${JADX_MCP_URL}" "${JADX_MCP_SHA256}" \
    "${BB_TOOLS_DIR}/jadx/jadx-headless-mcp-${JADX_MCP_VERSION}-all.jar"
}

install_capture() {
  make_venv "${BB_TOOLS_DIR}/venv-mitmproxy" "mitmproxy==${MITMPROXY_VERSION}"
  "${BB_TOOLS_DIR}/venv-mitmproxy/bin/mitmdump" --version | head -1
}

install_native() {
  needs native GHIDRA_ZIP_URL GHIDRA_SHA256 || return 0
  apt-get -y install --no-install-recommends openjdk-21-jdk-headless
  local zip="${BB_TOOLS_DIR}/.cache/ghidra_${GHIDRA_VERSION}.zip"
  fetch_verified "${GHIDRA_ZIP_URL}" "${GHIDRA_SHA256}" "${zip}"
  if [[ ! -d "${BB_TOOLS_DIR}/ghidra_${GHIDRA_VERSION}_PUBLIC" ]]; then
    unzip -q "${zip}" -d "${BB_TOOLS_DIR}"
  fi
  [[ -x "${BB_TOOLS_DIR}/ghidra_${GHIDRA_VERSION}_PUBLIC/support/analyzeHeadless" ]] \
    || die "Ghidra extraído não contém support/analyzeHeadless."
  rm -f "${zip}"
}

install_elf() {
  apt-get -y install --no-install-recommends build-essential python3-dev libssl-dev libffi-dev
  make_venv "${BB_TOOLS_DIR}/venv-pwntools" \
    "pwntools==${PWNTOOLS_VERSION}" "pyelftools==${PYELFTOOLS_VERSION}" "unicorn==${UNICORN_VERSION}"
}

install_crash() {
  apt-get -y install --no-install-recommends gdb
  needs crash PWNDBG_TARBALL_URL PWNDBG_SHA256 || return 0
  local tgz="${BB_TOOLS_DIR}/.cache/pwndbg_${PWNDBG_VERSION}.tar.xz"
  fetch_verified "${PWNDBG_TARBALL_URL}" "${PWNDBG_SHA256}" "${tgz}"
  install -d -m 755 "${BB_TOOLS_DIR}/pwndbg"
  tar -xf "${tgz}" -C "${BB_TOOLS_DIR}/pwndbg" --strip-components=1 --no-same-owner
  rm -f "${tgz}"
}

install_firmware() {
  apt-get -y install --no-install-recommends \
    cargo rustc pkg-config build-essential libfontconfig1-dev liblzma-dev libbz2-dev \
    e2fsprogs lz4 lzop 7zip unar zstd squashfs-tools android-sdk-libsparse-utils
  CARGO_HOME="${BB_TOOLS_DIR}/cargo" cargo install --locked --root "${BB_TOOLS_DIR}/binwalk" \
    binwalk --version "${BINWALK_VERSION}"
  make_venv "${BB_TOOLS_DIR}/venv-unblob" "unblob==${UNBLOB_VERSION}"
  rm -rf "${BB_TOOLS_DIR}/cargo/registry"
}

install_jsrecovery() {
  needs jsrecovery WAKARU_URL WAKARU_SHA256 || return 0
  fetch_verified "${WAKARU_URL}" "${WAKARU_SHA256}" "${BB_TOOLS_DIR}/wakaru/wakaru"
  chmod 755 "${BB_TOOLS_DIR}/wakaru/wakaru"
}

install -d -m 755 "${BB_TOOLS_DIR}" "${BB_TOOLS_DIR}/.cache"
for c in "${SELECTED[@]}"; do
  log "== ${c} =="
  "install_${c}"
done
rm -rf "${BB_TOOLS_DIR}/.cache"
chown -R root:root "${BB_TOOLS_DIR}"
chmod -R go-w "${BB_TOOLS_DIR}"

if [[ ${#SKIPPED[@]} -gt 0 ]]; then
  warn "componentes pulados por falta de URL/hash: ${SKIPPED[*]}"
  warn "preencha versions.env e rode novamente só eles, ex.: sudo $0 native"
fi
log "fase 2 concluída. Próximo: provision/30-workspace.sh"

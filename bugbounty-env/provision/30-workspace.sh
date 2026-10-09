#!/usr/bin/env bash
# Fase 3 – workspace, arquivo de ambiente, utilitários bb-* e pacote Python bbrea.
# Executar como root (sudo). Gera /etc/bb/rea-bb.env apenas com as ferramentas
# que realmente existem no disco.
source "$(dirname "$0")/../lib/common.sh"

require_root
require_debian
id "${BB_USER}" &>/dev/null || die "usuário ${BB_USER} não existe; rode 00-hardening.sh antes."

confirm_plan "workspace e configuração" \
  "${BB_WORK_DIR}/{targets,captures,output,scope} com dono ${BB_USER} e modo 700" \
  "${BB_ENV_FILE} (root:${BB_USER} 640) com as variáveis REA_* das ferramentas instaladas" \
  "utilitários em /usr/local/bin: bb-rea-mcp bb-chromium bb-vnc bb-check" \
  "venv ${BB_TOOLS_DIR}/venv-bbrea com o pacote bbrea (somente biblioteca padrão)" \
  "carregar ${BB_ENV_FILE} no ~/.bashrc de ${BB_USER}"

# 1. Diretórios de trabalho -----------------------------------------------------
install -d -m 700 -o "${BB_USER}" -g "${BB_USER}" "${BB_WORK_DIR}"
for d in targets captures output scope; do
  install -d -m 700 -o "${BB_USER}" -g "${BB_USER}" "${BB_WORK_DIR}/${d}"
done

# 2. Arquivo de ambiente --------------------------------------------------------
TMP_ENV="$(mktemp)"
emit() { printf 'export %s=%q\n' "$1" "$2" >> "${TMP_ENV}"; }
emit_if() { [[ -e "$2" ]] && emit "$1" "$2" || warn "não encontrado (ignorado): $1=$2"; }

{
  echo "# Gerado por 30-workspace.sh em $(date -u +%FT%TZ). Não guarde segredos aqui."
  echo "# Recarregue com: source ${BB_ENV_FILE}"
} > "${TMP_ENV}"
emit BB_WORK_DIR "${BB_WORK_DIR}"
emit BB_CDP_ENDPOINT "http://127.0.0.1:9222"
emit_if REA_BROWSER_EXECUTABLE /usr/bin/chromium
emit_if JAVA_HOME /usr/lib/jvm/java-21-openjdk-amd64
emit_if REA_JADX_MCP_JAR "${BB_TOOLS_DIR}/jadx/jadx-headless-mcp-${JADX_MCP_VERSION}-all.jar"
emit_if REA_MITMDUMP_COMMAND "${BB_TOOLS_DIR}/venv-mitmproxy/bin/mitmdump"
emit_if GHIDRA_INSTALL_DIR "${BB_TOOLS_DIR}/ghidra_${GHIDRA_VERSION}_PUBLIC"
emit_if REA_PWNTOOLS_PYTHON "${BB_TOOLS_DIR}/venv-pwntools/bin/python"
emit_if REA_PWNDBG_GDB /usr/bin/gdb
emit_if REA_BINWALK_COMMAND "${BB_TOOLS_DIR}/binwalk/bin/binwalk"
emit_if REA_UNBLOB_COMMAND "${BB_TOOLS_DIR}/venv-unblob/bin/unblob"
emit_if REA_FIRMWARE_PRLIMIT_COMMAND /usr/bin/prlimit
emit_if REA_WAKARU_COMMAND "${BB_TOOLS_DIR}/wakaru/wakaru"
emit_if REA_JAVASCRIPT_PRLIMIT_COMMAND /usr/bin/prlimit
cat >> "${TMP_ENV}" <<'EOF'
# pwndbg: ajuste conforme o layout do tarball extraído em /opt/bb-tools/pwndbg
# (ver docs/recorded-crashes.md do REA).
# export REA_PWNDBG_GDBINIT=/opt/bb-tools/pwndbg/.../gdbinit.py
# export REA_PWNDBG_VENV_PATH=/opt/bb-tools/pwndbg/...
# Ajustes opcionais de recursos do JADX:
# export REA_JADX_HEAP_MIB=4096
# export REA_JADX_ACTIVE_PROCESSOR_COUNT=4
EOF
install -d -m 750 -o root -g "${BB_USER}" "$(dirname "${BB_ENV_FILE}")"
install -m 640 -o root -g "${BB_USER}" "${TMP_ENV}" "${BB_ENV_FILE}"
rm -f "${TMP_ENV}"

# 3. Utilitários ---------------------------------------------------------------
for tool in bb-rea-mcp bb-chromium bb-vnc bb-check; do
  install -m 755 -o root -g root "${BB_ROOT}/bin/${tool}" "/usr/local/bin/${tool}"
done

# 4. Pacote Python bbrea --------------------------------------------------------
make_venv "${BB_TOOLS_DIR}/venv-bbrea" "${BB_ROOT}/bbrea"
ln -sfn "${BB_TOOLS_DIR}/venv-bbrea/bin/bbrea" /usr/local/bin/bbrea
chown -R root:root "${BB_TOOLS_DIR}/venv-bbrea"
chmod -R go-w "${BB_TOOLS_DIR}/venv-bbrea"

# 5. Shell do usuário -----------------------------------------------------------
BASHRC="/home/${BB_USER}/.bashrc"
LINE="[ -r ${BB_ENV_FILE} ] && . ${BB_ENV_FILE}"
grep -qxF "${LINE}" "${BASHRC}" 2>/dev/null || echo "${LINE}" >> "${BASHRC}"
chown "${BB_USER}:${BB_USER}" "${BASHRC}"

log "fase 3 concluída. Entre como ${BB_USER} e rode: bb-check"

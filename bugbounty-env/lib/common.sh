# shellcheck shell=bash
# Funções compartilhadas pelos scripts de provisionamento.
# Uso: source "$(dirname "$0")/../lib/common.sh"

set -Eeuo pipefail
umask 022

BB_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=../versions.env
source "${BB_ROOT}/versions.env"

log()  { printf '\033[1;34m[bb]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[bb][aviso]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[bb][erro]\033[0m %s\n' "$*" >&2; exit 1; }

trap 'die "falhou na linha ${LINENO}: ${BASH_COMMAND}"' ERR

require_root() {
  [[ ${EUID} -eq 0 ]] || die "execute como root (sudo $0)."
}

require_debian() {
  # shellcheck disable=SC1091
  source /etc/os-release
  [[ "${ID:-}" == "${BB_EXPECTED_OS_ID}" && "${VERSION_ID:-}" == "${BB_EXPECTED_OS_VERSION_ID}" ]] \
    || die "sistema esperado: ${BB_EXPECTED_OS_ID} ${BB_EXPECTED_OS_VERSION_ID}; encontrado: ${ID:-?} ${VERSION_ID:-?}."
  [[ "$(uname -m)" == "x86_64" ]] || die "arquitetura suportada: x86_64."
}

# Mostra o plano e pede confirmação explícita (BB_ASSUME_YES=1 pula).
confirm_plan() {
  local title="$1"; shift
  log "PLANO: ${title}"
  local item
  for item in "$@"; do printf '   - %s\n' "${item}"; done
  if [[ "${BB_ASSUME_YES:-0}" == "1" ]]; then
    warn "BB_ASSUME_YES=1: confirmação automática."
    return 0
  fi
  local answer
  read -r -p "Aplicar? digite 'sim' para continuar: " answer
  [[ "${answer}" == "sim" ]] || die "cancelado pelo usuário."
}

require_var() {
  local name="$1" hint="$2"
  [[ -n "${!name:-}" ]] || die "${name} está vazio em versions.env. ${hint}"
}

# Baixa uma URL HTTPS e só a move para o destino se o SHA-256 conferir.
# fetch_verified URL SHA256 DESTINO
fetch_verified() {
  local url="$1" sha="$2" dest="$3" tmp
  [[ "${url}" == https://* ]] || die "URL não-HTTPS recusada: ${url}"
  [[ "${sha}" =~ ^[0-9a-f]{64}$ ]] || die "SHA-256 inválido para ${url}"
  tmp="$(mktemp)"
  log "baixando ${url}"
  curl --proto '=https' --tlsv1.2 --fail --silent --show-error --location \
       --retry 3 --output "${tmp}" "${url}"
  if ! printf '%s  %s\n' "${sha}" "${tmp}" | sha256sum --check --status; then
    rm -f "${tmp}"
    die "SHA-256 NÃO confere para ${url}. Download descartado."
  fi
  install -D -m 0644 "${tmp}" "${dest}"
  rm -f "${tmp}"
  log "verificado: $(basename "${dest}")"
}

# Cria um venv isolado e instala pacotes com versões exatas.
make_venv() {
  local dir="$1"; shift
  if [[ ! -x "${dir}/bin/python" ]]; then
    python3 -m venv "${dir}"
  fi
  "${dir}/bin/python" -m pip install --quiet --upgrade pip
  "${dir}/bin/python" -m pip install --quiet "$@"
}

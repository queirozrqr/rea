# Ambiente de bug bounty com REA

Guia de consulta para subir, operar e manter um servidor dedicado que executa o
[REA](../README.md) (CLI e MCP) em recon de bug bounty.

> **Estado:** os arquivos deste diretório foram **gerados e revisados, mas nunca
> executados em um servidor real**. A única validação feita foi checagem de
> sintaxe dos scripts (`bash -n`) e os testes unitários do pacote `bbrea`. Siga o
> [checklist de aceite](#7-checklist-de-aceite) na primeira subida.

---

## 1. Decisão: onde rodar

**Recomendado: VPS dedicado, Debian 13, só para bug bounty.**

| Critério                                        | VPS dedicado (recomendado)                              | VM local                            |
| ----------------------------------------------- | ------------------------------------------------------- | ----------------------------------- |
| Isolamento da sua rede e dos seus dados         | Total, nada do alvo toca sua casa                       | Compartilha a rede doméstica e o IP |
| IP fixo (alguns programas pedem para cadastrar) | Sim                                                     | Não, em geral                       |
| Snapshots e restauração                         | No painel do provedor                                   | Depende do hypervisor               |
| Disponibilidade                                 | 24/7                                                    | Só com o PC ligado                  |
| Custo                                           | Mensal                                                  | Zero                                |
| Privacidade dos dados no disco                  | Provedor tem acesso físico (mitigar com volume cifrado) | Total                               |

Por que Debian 13 e não Ubuntu: no Ubuntu o Chromium só existe como _snap_, que
confina caminhos e perfis e complica o uso pelo REA. No Debian ele é pacote
`.deb` normal.

**Antes de contratar:** leia a política de uso aceitável (AUP) do provedor sobre
pesquisa de segurança. Recon passivo e testes autorizados em programas costumam
ser aceitos, mas a regra é do provedor.

### Dimensionamento

| Recurso     | Mínimo | Recomendado   | Motivo                                                   |
| ----------- | ------ | ------------- | -------------------------------------------------------- |
| vCPU        | 2      | **4**         | JADX e Ghidra consomem bastante CPU                      |
| RAM         | 4 GB   | **8 GB**      | JVMs do JADX/Ghidra e o Chromium                         |
| Disco       | 40 GB  | **80 GB SSD** | Ghidra (~1 GB), toolchain Rust, APKs e capturas          |
| Arquitetura | x86_64 | x86_64        | Wakaru, pwntools e firmware são verificados em Linux x64 |

---

## 2. Arquitetura

```
 Seu PC ──SSH (chave)──► VPS Debian 13  (firewall: entrada só 22/tcp)
   │                      │
   │ túnel opcional       ├─ usuário admin (sudo)  → só para provisionar/atualizar
   │ ssh -L 5900:…        └─ usuário hunter (sem sudo) → trabalho diário
   ▼                           │
 cliente VNC                   ├─ Claude Code ──stdio──► bb-rea-mcp ─► rea mcp
                               ├─ bbrea (Python) ─────► rea <cmd> --json
                               │
                               ├─ Chromium  CDP 127.0.0.1:9222 (sandbox ativo)
                               ├─ Xvfb + x11vnc 127.0.0.1:5900 (só p/ login manual)
                               ├─ JDK 21 + jadx-headless-mcp 0.7.1  (APK)
                               ├─ mitmproxy 12.2.3 (venv)            (capturas)
                               ├─ Ghidra 12.1.4                      (binários)
                               ├─ pwntools 4.15.0 / gdb / pwndbg     (ELF/crashes)
                               ├─ binwalk 3.1.0 / unblob 26.6.4      (firmware)
                               └─ Wakaru 1.13.0                      (recuperar JS)

 /opt/bb-tools  root:root 755 → ferramentas (hunter não altera)
 /srv/bb        hunter    700 → targets/ captures/ output/ scope/
 /etc/bb/rea-bb.env  root:hunter 640 → variáveis REA_*
```

Princípios:

- **Nenhum serviço exposto.** O MCP do REA usa stdio. CDP e VNC escutam só em
  `127.0.0.1`.
- **Menor privilégio.** O dia a dia roda como `hunter`, sem sudo. As ferramentas
  pertencem ao root.
- **Integridade da supply chain.** Versões exatas e SHA-256 conferido em todo
  download. O Node é verificado também por GPG. O npm roda com
  `--ignore-scripts`.
- **Escopo primeiro.** `bbrea` e `bb-chromium` recusam alvos fora de
  `scope/<programa>.txt`, com negação por padrão.

---

## 3. Conteúdo deste diretório

| Caminho                     | Função                                                                                  |
| --------------------------- | --------------------------------------------------------------------------------------- |
| `versions.env`              | **Fonte única** de versões, URLs e SHA-256                                              |
| `lib/common.sh`             | Funções comuns: confirmação de plano, download verificado, venv                         |
| `provision/00-hardening.sh` | Fase 0: pacotes, usuário `hunter`, SSH, firewall, fail2ban, sysctl, updates automáticos |
| `provision/10-node-rea.sh`  | Fase 1: Node 24.18.0 (SHA + GPG) e `rea-agents@6.0.0`                                   |
| `provision/20-providers.sh` | Fase 2: provedores (`web android capture native elf crash firmware jsrecovery`)         |
| `provision/30-workspace.sh` | Fase 3: `/srv/bb`, `/etc/bb/rea-bb.env`, utilitários `bb-*`, pacote `bbrea`             |
| `config/`                   | Arquivos de SSH, sysctl e fail2ban instalados pela fase 0                               |
| `bin/bb-rea-mcp`            | Inicia `rea mcp` com o ambiente (usado no registro do MCP)                              |
| `bin/bb-chromium`           | Chromium descartável por programa, CDP em loopback, escopo checado                      |
| `bin/bb-vnc`                | Tela virtual para login manual, acessível só por túnel SSH                              |
| `bin/bb-check`              | Checklist de aceite, somente leitura                                                    |
| `bbrea/`                    | Pacote Python (só biblioteca padrão) com escopo, pipelines e relatório                  |

Todos os scripts de provisionamento **mostram o plano e pedem que você digite
`sim`** antes de alterar o sistema, seguindo o mesmo princípio do `rea setup`.

---

## 4. Pré-requisitos (antes de subir)

1. **Par de chaves SSH** no seu PC, de preferência ed25519 com passphrase:
   `ssh-keygen -t ed25519`.
2. **VPS criado** com Debian 13 x86_64 e sua chave pública cadastrada.
3. **Usuário admin com sudo e chave SSH.** Se o provedor só entrega `root`:
   ```bash
   adduser admin && usermod -aG sudo admin
   install -d -m 700 -o admin -g admin /home/admin/.ssh
   cp /root/.ssh/authorized_keys /home/admin/.ssh/ && chown admin: /home/admin/.ssh/authorized_keys
   ```
   A fase 0 **aborta se for executada como root direto**, para evitar lockout.
4. **Preencher os hashes** que faltam em `versions.env`
   (ver [Como obter os hashes](#como-obter-os-hashes)).

### Como obter os hashes

`JADX_MCP_SHA256` já vem preenchido. É o mesmo valor auditado em
`src/android/JadxRelease.ts`. Os demais vêm das páginas oficiais de release:

| Variável                               | Onde obter                                                                                                                |
| -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| `GHIDRA_ZIP_URL` / `GHIDRA_SHA256`     | Release `Ghidra_12.1.4_build` em github.com/NationalSecurityAgency/ghidra/releases. As notas publicam o SHA-256 do `.zip` |
| `WAKARU_URL` / `WAKARU_SHA256`         | Release 1.13.0 do Wakaru, binário Linux x64                                                                               |
| `PWNDBG_TARBALL_URL` / `PWNDBG_SHA256` | Release `2026.09.15` em github.com/pwndbg/pwndbg/releases, tarball portátil x86_64                                        |

Se a release não publicar o hash, baixe o arquivo **no seu PC**, confira a
assinatura ou proveniência que o projeto oferecer e calcule com
`sha256sum arquivo`. Componentes com hash vazio são **pulados** com aviso; nada
é instalado sem verificação.

---

## 5. Passo a passo da subida

Tempo estimado: 30 a 60 minutos. A maior parte é compilação do binwalk e
downloads.

```bash
# No seu PC: enviar este diretório para o servidor
scp -r bugbounty-env admin@SERVIDOR:~/

# No servidor, como admin
ssh admin@SERVIDOR
cd ~/bugbounty-env
chmod +x provision/*.sh bin/*

# Fase 0 – hardening (opcional: restringir SSH ao seu IP)
sudo BB_SSH_ALLOW_FROM="SEU.IP.PUBLICO/32" ./provision/00-hardening.sh
#   >>> ANTES DE FECHAR A SESSÃO: teste em outro terminal
#       ssh admin@SERVIDOR   e   ssh hunter@SERVIDOR
#   >>> Snapshot no painel: "00-base-limpa"

sudo ./provision/10-node-rea.sh          # Fase 1 – Node + REA
sudo ./provision/20-providers.sh         # Fase 2 – todos os provedores
#    ou parcial:  sudo ./provision/20-providers.sh web android capture
sudo ./provision/30-workspace.sh         # Fase 3 – workspace, env, bb-*, bbrea

# Validação como hunter
ssh hunter@SERVIDOR
bb-check
#   >>> Snapshot no painel: "01-rea-pronto"
```

### Fase 4: integrar ao agente (Claude Code)

Como `hunter`, instale o Claude Code seguindo a documentação oficial
(https://code.claude.com/docs) e registre o REA pelo wrapper:

```bash
claude mcp add --scope user rea -- /usr/local/bin/bb-rea-mcp
claude mcp list
```

O wrapper usa o REA **fixado em /opt/bb-tools**. Isso difere do `npx rea-agents`
que o `rea setup` grava: nada é baixado do npm a cada inicialização e as
variáveis `REA_*` são carregadas de `/etc/bb/rea-bb.env`. Para instalar só as
instruções (skill) do REA para o agente, veja "skill-only installation" em
`docs/installation.md`.

### Opcional: volume cifrado para `/srv/bb`

O disco do VPS fica sob controle do provedor. Para proteger capturas, que podem
conter tokens, use um volume adicional com LUKS, destravado manualmente após cada
boot:

```bash
sudo cryptsetup luksFormat /dev/sdX          # volume extra do provedor
sudo cryptsetup open /dev/sdX bbdata
sudo mkfs.ext4 /dev/mapper/bbdata
sudo mount /dev/mapper/bbdata /srv/bb && sudo chown hunter: /srv/bb && sudo chmod 700 /srv/bb
```

---

## 6. Uso diário

### Novo programa

```bash
bbrea init acme                      # cria targets/ captures/ output/ e scope/acme.txt
nano /srv/bb/scope/acme.txt          # copie o escopo EXATO da página do programa
bbrea scope-check acme https://app.acme.com
```

Formato do escopo, com negação por padrão:

```
app.acme.com            # host exato
*.api.acme.com          # subdomínios (não inclui api.acme.com)
198.51.100.0/24         # rede
!admin.api.acme.com     # exclusão (o host e seus subdomínios); sempre vence
```

### Recon web

```bash
# terminal 1 – navegador headless com perfil descartável do programa
bb-chromium acme https://app.acme.com

# terminal 2 – pipeline: bundle → captura passiva → export do JS → análise
bbrea web acme https://app.acme.com
# saída: /srv/bb/output/acme/<UTC>-web/{NN-*.json, summary.json, report.md}
```

O `report.md` lista source maps candidatos, caminhos de API e URLs separados
entre **no escopo** e **fora do escopo**. Valores de query string ficam sempre
como `REDACTED`.

**Fluxos com login** (área autenticada):

```bash
bb-vnc                                           # servidor, terminal 1
ssh -N -L 5900:127.0.0.1:5900 hunter@SERVIDOR    # seu PC
# abra um cliente VNC em 127.0.0.1:5900, depois:
bb-chromium acme https://app.acme.com --headful  # servidor, terminal 2
# faça login pelo VNC; então:  bbrea web acme https://app.acme.com/dashboard
```

### Outros alvos

```bash
cp app.apk /srv/bb/targets/acme/
bbrea apk acme /srv/bb/targets/acme/app.apk --search Api --search Auth --search WebView

bbrea capture acme /srv/bb/captures/acme/sessao.har            # HAR exportado do navegador/Burp
bbrea capture acme /srv/bb/captures/acme/fluxo.mitm --format mitmproxy
bbrea js acme /srv/bb/targets/acme/app.asar                     # Electron
bbrea firmware acme /srv/bb/targets/acme/fw.bin
```

Os demais comandos do REA (Ghidra, `inspect-binary-layout`,
`recover-javascript-sources` etc.) podem ser usados direto com `rea <comando>`
ou pelo agente via MCP. O ambiente já exporta as variáveis necessárias.

### Códigos de saída do `bbrea`

| Código | Significado                                                      |
| ------ | ---------------------------------------------------------------- |
| 0      | sucesso (passos opcionais podem ter falhado; ver `summary.json`) |
| 1      | erro de entrada, workspace, REA ou passo obrigatório             |
| 3      | **alvo fora do escopo**: nada foi executado contra ele           |

---

## 7. Checklist de aceite

Na primeira subida e depois de cada atualização:

- [ ] `bb-check` sem falhas
- [ ] `ss -tlnp` mostra só `:22` fora do loopback
- [ ] `sudo ufw status verbose`: entrada negada, só 22/tcp liberada
- [ ] `ssh root@SERVIDOR` e login por senha são **recusados**
- [ ] Web: `bb-chromium lab http://127.0.0.1:3000` com um alvo de laboratório
      **local** (ex.: OWASP Juice Shop) e `bbrea web lab http://127.0.0.1:3000`
      (escopo `127.0.0.1`)
- [ ] Android: `bbrea apk` com o APK público Appium ApiDemos (citado em
      `third_party/README.md`). O bridge JADX do REA foi verificado
      oficialmente só em macOS; este passo confirma o comportamento no Linux
- [ ] Captura: `bbrea capture` com um HAR de exemplo
- [ ] Ghidra: `rea doctor --provider ghidra --json`
- [ ] MCP: no Claude Code, `/mcp` lista `rea` conectado
- [ ] Snapshot "01-rea-pronto"

Nunca valide o ambiente contra um alvo real de programa.

---

## 8. Operação e manutenção

| Tarefa                      | Como                                                                                             |
| --------------------------- | ------------------------------------------------------------------------------------------------ |
| Patches de segurança do SO  | Automáticos (`unattended-upgrades`). Revise `/var/log/unattended-upgrades/`                      |
| Atualizar o REA             | Mude `REA_VERSION` em `versions.env`, `sudo ./provision/10-node-rea.sh`, `bb-check`, snapshot    |
| Atualizar um provedor       | Mude versão e hash em `versions.env`, `sudo ./provision/20-providers.sh <comp>`                  |
| Fim de um programa          | `rm -rf /srv/bb/captures/<prog>/chromium-profile` (cookies/sessões). Arquive ou apague `output/` |
| Suspeita de comprometimento | Restaure o snapshot "01-rea-pronto" e troque as chaves SSH                                       |
| Backup                      | Só `scope/` e anotações próprias. Capturas de alvos são descartáveis e sensíveis                 |

Não sincronize `/srv/bb` com nuvem pessoal e higienize qualquer captura antes de
anexar a um relatório.

---

## 9. Modelo de segurança e riscos

| Risco                                                                      | Mitigação aplicada                                                                                                                                                                           |
| -------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| APK, binário ou firmware malicioso explora o parser (JADX, Ghidra, unblob) | VPS isolado, usuário sem sudo, ferramentas root-owned, snapshot para restaurar; o unblob mantém o sandbox Landlock                                                                           |
| CDP exposto daria controle total do navegador                              | `--remote-debugging-address=127.0.0.1`, firewall, Chromium só sob demanda, `bb-check` alerta                                                                                                 |
| Página hostil escapa do navegador                                          | Sandbox do Chromium **ativo** (sysctl `unprivileged_userns_clone=1`); nunca `--no-sandbox`                                                                                                   |
| Pacote npm ou PyPI comprometido                                            | Versões exatas, `npm --ignore-scripts`, `bbrea` sem dependências. Para endurecer mais: gere `requirements.txt` com hashes (`pip-compile --generate-hashes`) e instale com `--require-hashes` |
| Download adulterado                                                        | `fetch_verified`: HTTPS obrigatório e SHA-256 antes de usar; Node também por GPG                                                                                                             |
| Teste fora do escopo                                                       | `bbrea`/`bb-chromium` checam o escopo antes de rodar e **revalidam a URL atual da aba** (redirects)                                                                                          |
| Vazamento de tokens em relatórios                                          | `report.md` substitui query e fragmento por `REDACTED`. Arquivos de saída com modo 600                                                                                                       |
| Lockout do SSH                                                             | A fase 0 exige admin com chave, valida `sshd -t` antes do reload e orienta a testar antes de fechar a sessão                                                                                 |
| Força bruta no SSH                                                         | Só chave pública, `ufw limit`, fail2ban com banimento progressivo                                                                                                                            |

O REA **não é sandbox** (veja o `SECURITY.md` do projeto). A fronteira de
isolamento é o VPS dedicado. Não guarde nele credenciais pessoais, chaves de
outros sistemas ou tokens de programas além do necessário.

---

## 10. Limitações conhecidas

- Os scripts nunca foram executados em um servidor real. Espere ajustes finos na
  primeira subida, como nomes de pacotes do Debian 13 ou a versão do Rust exigida
  pelo binwalk 3.1.0.
- `binwalk` é compilado com o `cargo` do Debian. Se a versão do Rust da distro
  for antiga demais, instale o Rust via `rustup` como root em
  `/opt/bb-tools/rustup` e repita a fase 2 do componente `firmware`.
- O caminho do `gdbinit.py` e do venv do pwndbg depende do layout do tarball.
  Ajuste `REA_PWNDBG_GDBINIT` e `REA_PWNDBG_VENV_PATH` em `/etc/bb/rea-bb.env`
  após extrair.
- O GDB do Debian 13 é mais novo que o verificado pelo REA (13.1). O REA informa
  a divergência no resultado.
- A captura web do REA **descarta cookies, cabeçalhos de autorização e valores
  de corpo** por design. Para manipular requisições, use Burp ou Caido.
- `bbrea` lê do JSON do REA apenas `targets[].target_id` e `targets[].url`, que
  são campos do contrato `list_browser_targets`. O resto é preservado sem
  interpretação, e o relatório é uma extração genérica para revisão manual.

---

## 11. Desenvolvimento do `bbrea`

```bash
cd bugbounty-env/bbrea
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

O pacote usa só a biblioteca padrão, Python 3.11 ou mais recente. Os testes
cobrem escopo (curingas, exclusões, CIDR, URLs ambíguas, negação por padrão),
confinamento de caminhos (`..` e symlinks), endpoint CDP só em loopback,
argumentos sem shell, seleção de aba e higienização do relatório.

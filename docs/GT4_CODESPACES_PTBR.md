# Como iniciar a versão jogável no GitHub Codespaces

A base deste fork é o **NFSU2 Web**, não um jogo refeito do zero. Seu código aberto executa a versão PC de Underground 2 traduzida para WebAssembly, renderiza por WebGPU e precisa dos arquivos de uma instalação legítima do jogo. O repositório **não contém** nem distribui esses arquivos.

## Passo 1 — Usar a branch certa

No Codespaces aberto para seu fork, use a branch `nfsu2-gt4-web`. Pelo terminal:

```bash
git fetch origin nfsu2-gt4-web
git switch nfsu2-gt4-web
git pull --ff-only origin nfsu2-gt4-web
```

Se você tiver alterações locais não salvas, não as descarte: preserve-as antes da troca. Nunca force alterações sobre a `main`.

## Passo 2 — Preparar o ambiente, mesmo sem o jogo

```bash
bash web/tools/gt4-codespace.sh prepare
```

O comando testa as ferramentas já disponíveis e, se faltarem `rustc` e `cargo`, instala automaticamente a toolchain oficial Rust via `rustup` em `~/.cargo/`, **sem `sudo`**. Também prepara em pastas locais o Python e o WASI SDK 34, instala as dependências npm e verifica/compila **a interface Web**. Ele **não** compila o jogo original, não inicia Bayview e não baixa conteúdo da EA. Um Codespace Linux x86_64 com Python 3, Node.js 20+, `curl` e `tar` é o alvo. O modo `check` é apenas diagnóstico: não instala ferramentas.

O Windows local **não precisa de acesso de administrador** para este fluxo em nuvem.

## Diagnóstico sem executar a ISO (opcional)

Quando uma imagem de disco obtida de uma fonte autorizada estiver dentro do Codespaces, é possível inspecionar o índice ISO-9660 **sem montar, extrair ou executar** seu conteúdo:

```bash
python3 web/tools/gt4-media-doctor.py ".nfsu2-local/NFSUG2_DISK1.iso" --archives
```

O comando informa os nomes na raiz, identifica indícios de um disco instalador (por exemplo `SETUP.EXE`) e avisa quando não há `CARS/`, `GLOBAL/` e `TRACKS/` na raiz. A opção `--archives` lê somente o índice central de arquivos `.ZIP` contidos na imagem, inclusive `COMPRESSED.ZIP`, sem descompactar nem copiar os arquivos. Se ele não reconhecer o ZIP, pode ser um formato proprietário ou mídia dividida entre discos. Isso não permite concluir que os dados do jogo estão completos. Também aceita pastas do jogo já extraídas:

```bash
python3 web/tools/gt4-media-doctor.py ".nfsu2-local/game"
```

Para analisar os arquivos de controle do instalador, incluindo o manifesto `COMMON_FILELIST.TXT` e os primeiros 64 bytes de `BIN.DAT`, execute:

```bash
python3 web/tools/gt4-media-doctor.py ".nfsu2-local/NFSUG2_DISK1.iso" --installer-info
```

O comando não executa `SETUP.EXE`, não monta a ISO e não extrai os arquivos. A assinatura de `BIN.DAT` é apenas um indício de formato, não uma verificação completa. As linhas de `COMMON_FILELIST.TXT` são limitadas para evitar saída excessiva.

Nesse segundo caso, verifica a presença de pastas essenciais, o tamanho e o SHA-256 do `SPEED2.EXE`. **Código de saída 2 significa que a mídia ainda não está pronta; não indica um erro de execução do jogo.** O verificador lê apenas metadados da ISO; não verifica malware, licenças, integridade da instalação completa, nem oferece suporte a toda imagem UDF/Joliet. Não substitui o comando `check` nem executa instaladores.

**Não tente contornar bloqueios do Controle Inteligente de Aplicativos do Windows.** O diagnóstico pode ser feito no Linux do Codespaces quando o arquivo for transferido privadamente. Mantenha a pasta `.nfsu2-local` fora do Git.

## Passo 3 — Colocar seus arquivos legítimos no Codespace

Use uma cópia original do Need for Speed Underground 2 para PC, versão norte-americana 1.2, conforme o README do projeto. O arquivo `SPEED2.EXE` obrigatório tem **4.800.512 bytes** e SHA-256:

`f9dd86c054878ce6276beb07c1fd61874f7a1e4bf1f241b084c65b73e24168a7`

A estrutura deve ficar **dentro do Codespace**, fora do controle de versão:

```text
.nfsu2-local/
  game/
    SPEED2.EXE
    GLOBAL/
    CARS/
    TRACKS/
    ... demais arquivos originais do jogo ...
```

Pode copiar uma pasta ou enviar um ZIP para dentro do Codespace pelo explorador de arquivos, e descompactá-lo lá com ferramentas do Linux; depois certifique-se de que `SPEED2.EXE` esteja diretamente dentro de `game/`, sem uma pasta intermediária. A pasta `.nfsu2-local/` já está no `.gitignore`.

**Importante:** não faça commit, push, release, publicação ou compartilhamento público dos dados de jogo, executáveis ou arquivos derivados; o GitHub Codespace e seu encaminhamento de porta devem permanecer **privados**. Se o upload pelo navegador não comportar o tamanho da instalação, será necessário escolher outro meio privado de transferência que você controle. Não obtenha os dados por downloads não autorizados.

## Passo 4 — Validar os dados e iniciar

```bash
bash web/tools/gt4-codespace.sh check
bash web/tools/gt4-codespace.sh run --port 8080
```

O primeiro comando confere ferramentas, tamanho e SHA-256 do executável. O segundo gera código C da cópia original, compila WASM, constrói a interface e o servidor Rust, e inicia a aplicação. A **primeira compilação pode consumir tempo e armazenamento consideráveis**.

Em **Ports** do Codespaces, mantenha a porta **8080 privada** e abra a URL de encaminhamento HTTPS no navegador. Como o site usa WebGPU, use Chrome/Edge com suporte WebGPU. Se a aba indicar problema de GPU, verifique as informações de diagnóstico sem alterar ou publicar os dados.

## Passo 5 — Critérios de jogabilidade

O jogo só será chamado de jogável depois que estes pontos tiverem sido verificados:

1. O WASM foi gerado sem falhas a partir da versão original compatível.
2. O servidor respondeu e a interface carregou no navegador pela porta privada.
3. O jogo entrou em Bayview e mostrou um carro controlável.
4. Teclado, câmera, direção, frenagem e pelo menos uma corrida funcionaram.
5. Modo visual Original e Studio foram comparados no mesmo local e sem erro WebGPU.
6. FPS, estabilidade e eventuais travamentos foram registrados.

**Situação atual:** a compilação da interface e o shader Studio já passaram em testes automatizados; **ainda não temos comprovação de uma sessão jogável em Bayview**. A última condição depende do proprietário fornecer o conjunto legítimo do jogo ao Codespace.

## Desenvolvimento seguinte

Após a primeira sessão jogável, compararemos dois registros do mesmo trecho com configurações Original e Studio; depois começaremos um aprimoramento de iluminação ou materiais por vez. Não devemos adicionar centenas de carros ou alterar a física antes de medir a estabilidade da base.

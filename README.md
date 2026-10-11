# Audita Aí;

**Confere você mesmo: a soma dos boletins de urna bate com o resultado oficial do TSE?**
Feito pelo [Garoto do Programa;](https://instagram.com/garotodoprograma) · Python puro, nada pra instalar.

```bash
python3 audita_ai.py        # Acre (o menor estado, ~17 MB)
python3 audita_ai.py RR     # qualquer estado (ZZ = eleitores no exterior)
python3 -m unittest -v      # roda os testes (sem internet)
python3 sabotagem.py        # tenta enganar o auditor (numa cópia)
```

## O que ele confere

| passo | o quê | por quê |
|---|---|---|
| 1 | baixa os **boletins de urna** do estado no [portal de dados abertos do TSE](https://dadosabertos.tse.jus.br) | é o mesmo resultado impresso e colado na porta de cada seção |
| 2 | **integridade:** o hash SHA-512 do arquivo é igual ao publicado pelo TSE? | prova que o arquivo que você tem é o oficial, sem um bit mudado |
| 3 | **consistência:** em cada seção, a soma dos votos bate com quem compareceu? | é a conta que qualquer fiscal faria na mão, só que em todas as seções |
| 4 | **totalização:** a soma de TODOS os boletins bate com o resultado oficial divulgado? Campo a campo e candidato a candidato | junta a ponta (cada urna) com o total que aparece no site de resultados |
| 5 | **estatística:** simula milhares de pesquisas (Monte Carlo) em cima da abstenção | mostra na prática de onde sai a tal da "margem de erro" |

O programa **nunca mostra nome de candidato**: só contagens ("12 de 12 candidatos batem"). Se alguma conferência falhar, ele avisa em vermelho e sai com código 1.

## Rodando no Acre (1º turno de 2026)

```
Audita Aí;  por Garoto do Programa · dados oficiais do TSE · 1º turno 2026

[1/5] baixando os boletins de urna de AC
   já baixado: bweb_1t_AC_051020261403.zip
   já baixado: bweb_1t_AC_051020261403.zip.sha512

[2/5] integridade: o arquivo é idêntico ao publicado? (SHA-512)
   TSE publicou: c095164588a0ad4f46717e081f51eab2…
   calculei:     c095164588a0ad4f46717e081f51eab2…
   ✓ idêntico ao publicado pelo TSE

[3/5] consistência: em cada seção, a soma dos votos bate com quem compareceu?
   Presidente           2.270 de 2.270   seções  ✓
   Governador           2.270 de 2.270   seções  ✓
   Senador              2.270 de 2.270   seções  ✓  (cada eleitor dá 2 votos)
   Deputado Federal     2.270 de 2.270   seções  ✓
   Deputado Estadual    2.270 de 2.270   seções  ✓

[4/5] totalização: a soma de TODOS os boletins bate com o resultado oficial?
   Presidente  ✓
      eleitores aptos                                     613.742 = 613.742    ✓
      compareceram                                        488.330 = 488.330    ✓
      faltaram                                            125.412 = 125.412    ✓
      votos em branco                                       5.579 = 5.579      ✓
      votos nulos (digitados + técnicos)                   13.685 = 13.685     ✓
      nominais (válidos + sub judice + nulos técnicos)    469.089 = 469.089    ✓
      votos de cada candidato                                  12 de 12      ✓
   … (Governador, Senador, Deputado Federal e Deputado Estadual: tudo ✓)
   ✓ tudo bateu

   raio-X do estado
   2.270 seções · 613.742 aptos · 125.412 faltaram → abstenção de 20,43%
   menos faltosos: Rodrigues Alves (16,1%), Mâncio Lima (17,5%), Senador Guiomard (18,6%)
   mais faltosos:  Santa Rosa Do Purus (26,6%), Feijó (25,0%), Jordão (24,8%)

[5/5] e se fosse uma pesquisa? 5.000 sorteios de 2.000 eleitores
    16,9% 
    17,4% 
    17,9% █
    18,4% ███
    18,9% ██████████
    19,4% █████████████████████
    19,9% █████████████████████████████████
    20,4% ████████████████████████████████████████
    20,9% ███████████████████████████████████
    21,4% ███████████████████████
    21,9% ██████████
    22,4% ███
    22,9% █
    23,4% 
    23,9% 
   valor real: 20,43%  ·  margem pela fórmula: ±1,8 pontos
   95,3% das 5.000 pesquisas simuladas caíram dentro da margem

   não é pesquisa nem previsão: é matemática em cima de um resultado que já aconteceu.
   confere você também;)  github.com/garotodoprograma404/audita-ai
```

## Resultados: 6 estados (1º turno 2026)

Vocês pediram nos comentários e eu rodei. A saída completa de cada estado está em [`resultados/`](resultados/).

| estado | seções | hash | urna por urna | soma × oficial |
|---|---:|:---:|:---:|:---:|
| AC | 2.270 | ✓ | ✓ | ✓ |
| PA | 20.827 | ✓ | ✓ | ✓ |
| BA | 35.476 | ✓ | ✓ | ✓ |
| MG | 52.062 | ✓ | ✓ | ✓ |
| RJ | 37.675 | ✓ | ✓ | ✓ |
| SP | 103.656 | ✓ | ✓ | ✓ |
| **total** | **251.966** | | | **tudo bateu** |

No caminho, o Pará e São Paulo acharam **dois bugs meus** com voto de legenda (os dois explicados logo abaixo, em "Totalização"). Nenhum era da eleição; os dois foram corrigidos, com teste.

## Como funciona (pra quem quer entender o algoritmo)

**Leitura.** Cada linha do CSV é *uma seção × um cargo × um votável* (candidato, legenda, branco ou nulo). O arquivo é lido **linha por linha** de dentro do zip (streaming), sem pandas e sem descompactar no disco, então roda até em computador fraquinho. O TSE usa `latin-1` e `;`. E o CSV entrega tudo como **texto**: `"5" + "2"` dá `"52"`, então converte com `int()` antes de somar.

**Consistência.** Soma `QT_VOTOS` de cada (seção, cargo) e compara com `QT_COMPARECIMENTO × votos por eleitor`. Os votos por eleitor vêm da **regra da eleição** (constante `VOTOS_POR_ELEITOR`): em 2026 o Senado renova 2/3, são duas vagas por estado, então no Senador cada eleitor dá **2 votos**. Os dados confirmam a regra; não é a regra que sai dos dados.

**Totalização.** Baixa o mesmo JSON que alimenta o site [resultados.tse.jus.br](https://resultados.tse.jus.br) e compara com a soma dos boletins. Dois detalhes que pegam muita gente:
- **Nulo técnico:** o boletim conta o voto no número que o eleitor digitou. Se aquele candidato teve o registro indeferido, o voto vira *nulo técnico* no resultado oficial. Por isso: nulos do boletim + votos em números que não estão na lista oficial = total de nulos oficial.
- **Anulado sub judice:** candidato com recurso pendente aparece na lista, mas os votos dele não entram nos *válidos*. Por isso a linha "nominais" soma válidos + sub judice + nulos técnicos.
- **Partido sub judice (voto de legenda):** vale o mesmo pro partido. Se o registro do partido está em julgamento, o boletim conta a legenda dele normalmente, mas o oficial zera os válidos (`tvtl`) e guarda o total apurado em `tval`. A primeira versão do Audita Aí comparava só com `tvtl` e acusou **491 votos de diferença no Pará** (1º turno 2026). Não era a eleição, era o programa: corrigido para comparar com os votos apurados, com teste.
- **Partido barrado (voto de legenda):** se o partido foi barrado da disputa daquele cargo, ele some da lista oficial, mas a urna pode ter aceitado o número dele. O boletim conta como legenda e o oficial joga em *nulo técnico*, igualzinho ao candidato barrado. Pegou em **São Paulo** (1º turno 2026, deputado federal, 1.173 votos). Também corrigido, com teste.

**Abstenção.** É calculada no cargo de Presidente, porque todo eleitor vota nele. Quem vota em trânsito só pode votar pra presidente, então o número de aptos muda de um cargo pro outro (dá pra ver isso no passo 4).

**Simulação de Monte Carlo.** Pega a abstenção real do estado (um fato que já aconteceu) e finge ser um instituto de pesquisa: entrevista 2.000 eleitores sorteados, anota quantos faltaram e repete 5.000 vezes. Depois compara com a fórmula da margem de erro com 95% de confiança:

```
margem = 1,96 × √( p × (1 − p) ÷ n )
```

Se a matemática estiver certa, **~95%** das pesquisas simuladas caem dentro da margem. E caem. A semente do sorteio é fixa (`--semente 2026`), então você roda e tira o mesmíssimo resultado.

## O que ele prova e o que ele NÃO prova

✓ **Prova** que o arquivo de boletins que você baixou é o publicado pelo TSE (hash), que cada boletim fecha a conta da própria seção e que a soma de todos os boletins é exatamente o resultado oficial divulgado.

✗ **Não prova** nada sobre o que acontece *antes* do boletim (a urna em si, o software dela, a votação). Pra isso existem outros mecanismos públicos: teste público de segurança, teste de integridade no dia da eleição (a antiga "votação paralela"), conferência do boletim impresso pelos fiscais de partido e assinatura digital de cada boletim. Bom próximo passo pra quem quiser evoluir o projeto: comparar com a **foto do boletim impresso** da sua seção.

## Sabotagem: tenta enganar o Audita Aí

Duvida que ele pega? Sabota. O `sabotagem.py` copia o boletim que você baixou, muda **UM voto na cópia** (o original e a urna ficam intactos) e roda as três conferências contra ela:

```bash
python3 sabotagem.py                  # tira 1 voto de um candidato e dá pra outro, na mesma seção
python3 sabotagem.py --golpe branco   # enfia 1 voto em branco a mais numa seção
```

Rodando no Acre:

| golpe | digital (SHA-512) | urna por urna | soma contra o oficial |
|---|---|---|---|
| `troca` | ✗ mudou | **✓ passa** (a seção continua fechando!) | ✗ 10 de 12 candidatos |
| `branco` | ✗ mudou | ✗ 2.269 de 2.270 | ✗ brancos 5.580 ≠ 5.579 |

O golpe da troca passa pela conta da urna, e é por isso que tem mais de uma conferência: **auditoria boa é camada em cima de camada**.

## Opções

```
python3 audita_ai.py [UF] [--turno 1|2] [--amostra 2000] [--rodadas 5000] [--semente 2026]
```

## Importante

- **Isto não é pesquisa eleitoral nem previsão.** Não tem candidato nenhum na simulação: ela só usa a abstenção, um resultado que já aconteceu, pra ensinar estatística.
- Os dados ficam na pasta `dados/`, que não vai pro Git: cada um baixa direto da fonte oficial.
- Fontes: Tribunal Superior Eleitoral, portal de dados abertos (*Resultados - 2026 - Boletim de Urna*) e site oficial de resultados.

## Licença

MIT: usa, estuda, muda e compartilha. Se melhorar, manda um pull request;)

---
segue o garoto;)  ·  [@garotodoprograma](https://instagram.com/garotodoprograma)

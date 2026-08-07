# Gera o dataset de audio de teste (WAV 16 kHz mono) via SAPI local.
# Vozes: Microsoft Maria/Daniel (pt-BR), Zira/David (en-US). Sem voz pt-PT instalada.
# Saida: bench\audio\*.wav + bench\refs.json
# NOTA: voz sintetica valida o PIPELINE; o A/B real de sotaque exige a voz do Ricardo
#       (gravar com scripts\record_test_audio.py).

Add-Type -AssemblyName System.Speech

$frases = @(
    @{ id = "pt01"; lang = "pt"; voice = "Microsoft Maria";  text = "Amanhã de manhã vou correr na praia da Rocha com o pessoal do clube." },
    @{ id = "pt02"; lang = "pt"; voice = "Microsoft Maria";  text = "A reunião foi remarcada para quinta-feira às três e meia da tarde." },
    @{ id = "pt03"; lang = "pt"; voice = "Microsoft Maria";  text = "Você pode me enviar o relatório de vendas do segundo trimestre?" },
    @{ id = "pt04"; lang = "pt"; voice = "Microsoft Maria";  text = "O coração da questão é a proteção dos dados pessoais dos usuários." },
    @{ id = "pt05"; lang = "pt"; voice = "Microsoft Maria";  text = "Choveu muito em Portimão, mas o fim de semana promete sol e calor." },
    @{ id = "pt06"; lang = "pt"; voice = "Microsoft Daniel"; text = "Preciso agendar uma consulta com o doutor Magalhães na próxima semana." },
    @{ id = "pt07"; lang = "pt"; voice = "Microsoft Daniel"; text = "A aplicação transforma voz em texto com pontuação automática e baixa latência." },
    @{ id = "pt08"; lang = "pt"; voice = "Microsoft Daniel"; text = "São vinte e três euros e cinquenta cêntimos, com desconto de dez por cento." },
    @{ id = "pt09"; lang = "pt"; voice = "Microsoft Daniel"; text = "Hum, deixa eu pensar, é, acho que a gente podia, tipo, adiar essa decisão." },
    @{ id = "pt10"; lang = "pt"; voice = "Microsoft Maria";  text = "Nova linha. O segundo parágrafo começa aqui, com iniciais maiúsculas." },
    @{ id = "en01"; lang = "en"; voice = "Microsoft Zira";   text = "The quarterly report shows a twelve percent increase in active users." },
    @{ id = "en02"; lang = "en"; voice = "Microsoft David";  text = "Please schedule the meeting for Thursday at half past three." },
    @{ id = "en03"; lang = "en"; voice = "Microsoft Zira";   text = "Latency below three hundred milliseconds is the target for this application." }
)

$outDir = Join-Path $PSScriptRoot "..\bench\audio" | Resolve-Path -ErrorAction SilentlyContinue
if (-not $outDir) { $outDir = New-Item -ItemType Directory -Force (Join-Path $PSScriptRoot "..\bench\audio") }

$refs = @{}
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)

# System.Speech só seleciona as vozes "Desktop" (as OneCore aparecem mas lançam exceção)
$desktopMap = @{
    "Microsoft Maria"  = "Microsoft Maria Desktop"
    "Microsoft Daniel" = "Microsoft Maria Desktop"   # sem Daniel Desktop; Maria cobre pt-BR
    "Microsoft Zira"   = "Microsoft Zira Desktop"
    "Microsoft David"  = "Microsoft David Desktop"
}

foreach ($f in $frases) {
    $wav = Join-Path $outDir ($f.id + ".wav")
    $voice = $desktopMap[$f.voice]
    try { $synth.SelectVoice($voice) } catch { Write-Warning "Voz $voice indisponível, usando padrão"; }
    $synth.SetOutputToWaveFile($wav, $fmt)
    $synth.Speak($f.text)
    $synth.SetOutputToNull()
    $refs[$f.id] = @{ lang = $f.lang; text = $f.text; voice = $f.voice }
    Write-Host "OK $($f.id) ($($f.voice))"
}
$synth.Dispose()

$refsPath = Join-Path $outDir "..\refs.json"
$refs | ConvertTo-Json -Depth 3 | Set-Content -Encoding UTF8 $refsPath
Write-Host "refs.json gravado em $refsPath ($($frases.Count) frases)"

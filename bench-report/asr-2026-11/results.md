# Raw results (tools/bench_asr.py)

## offline (FLEURS test, 100 phrases per language)

| run | ru WER | ru CER | ru RTFx | en WER | en RTFx | de WER | de RTFx | load s | CPU % mean | RSS peak MB | VRAM MB |
|---|---|---|---|---|---|---|---|---|---|---|---|
| offline-canary-int8-cpu | 7.64 | 2.47 | 5.7 | 6.55 | 6.4 | — | — | 1.91 | 10.7 | 1718.0 | — |
| offline-gigaam-ctc-int8-cpu | 5.44 | 1.8 | 31.6 | — | — | — | — | 0.67 | 11.3 | 460.0 | — |
| offline-gigaam-rnnt-cpu | 5.03 | 1.77 | 18.7 | — | — | — | — | 1.26 | 11.1 | 1121.0 | — |
| offline-gigaam-rnnt-gpu | 5.03 | 1.77 | 80.7 | — | — | — | — | 3.22 | 3.7 | 1520.0 | 2499 |
| offline-gigaam-rnnt-int8-cpu | 5.03 | 1.71 | 29.9 | — | — | — | — | 0.68 | 10.9 | 462.0 | — |
| offline-nemotron-1120-cpu | 11.23 | 4.47 | 8.8 | 12.2 | 8.8 | — | — | 1.48 | 9.3 | 946.0 | — |
| offline-nemotron-160-cpu | 13.18 | 5.08 | 2.1 | 13.34 | 2.1 | — | — | 1.47 | 9.6 | 878.0 | — |
| offline-nemotron-560-cpu | 12.36 | 4.81 | 5.7 | 11.95 | 5.7 | — | — | 1.43 | 9.3 | 879.0 | — |
| offline-parakeet-fp32-cpu | 5.79 | 1.65 | 10.5 | 5.45 | 10.5 | — | — | 3.46 | 11.3 | 2836.0 | — |
| offline-parakeet-fp32-gpu | 5.79 | 1.65 | 94.1 | 5.45 | 87.8 | — | — | 4.11 | 4.8 | 1449.0 | 3727 |
| offline-parakeet-int8-cpu | 7.85 | 2.44 | 20.0 | 8.07 | 19.9 | — | — | 1.26 | 10.7 | 1183.0 | — |
| offline-qwen3-0.6b-gpu | 9.95 | 3.27 | 6.2 | 8.36 | 8.5 | — | — | 14.32 | 8.8 | 2388.0 | 2149 |
| offline-qwen3-1.7b-gpu-card10 | 5.79 | 1.83 | 5.9 | 6.12 | 8.0 | — | — | 13.68 | 8.5 | 4976.0 | 4845 |
| offline-qwen3-1.7b-gpu | 5.79 | 1.83 | 5.9 | 6.12 | 8.0 | — | — | 15.89 | 8.4 | 4532.0 | 4846 |
| offline-tone-cpu | 12.82 | 4.79 | 19.1 | — | — | — | — | 1.35 | 8.3 | 452.0 | — |
| offline-ultra-fp16-gpu | 7416.92 | 4218.06 | 8.0 | 5276.27 | 7.9 | — | — | 3.91 | 3.1 | 1936.0 | 2579 |
| offline-ultra-fp32-cpu | 5.18 | 1.79 | 10.4 | 5.28 | 10.5 | — | — | 2.2 | 11.3 | 2843.0 | — |
| offline-ultra-fp32-gpu | 5.18 | 1.79 | 91.8 | 5.28 | 88.1 | — | — | 5.51 | 4.7 | 1502.0 | 3735 |
| offline-ultra-int8-cpu | 7.44 | 2.25 | 19.9 | 6.97 | 19.9 | — | — | 1.29 | 10.8 | 1186.0 | — |
| offline-whisper-turbo-cpu | 5.13 | 1.55 | 1.8 | 6.04 | 1.6 | — | — | 3.91 | 12.4 | 1412.0 | — |
| offline-whisper-turbo-gpu | 5.03 | 1.46 | 46.1 | 5.83 | 47.9 | — | — | 3.5 | 3.3 | 1778.0 | 2481 |

## longform (public meeting recordings, WER % / RTFx)

| run | en-ami-ES2004a | en-notsofar-MTG32000 | ru-mtedx-talk | ru-yodas-webinar |
|---|---|---|---|---|
| longform-gigaam-ctc-int8-cpu | — | — | 16.55 / 19.9 | 37.65 / 16.0 |
| longform-gigaam-rnnt-gpu | — | — | 14.99 / 27.3 | 37.95 / 27.5 |
| longform-gigaam-rnnt-int8-cpu | — | — | 15.37 / 19.1 | 38.03 / 15.5 |
| longform-nemotron-560-cpu | 34.39 / 6.0 | 58.81 / 6.0 | 24.45 / 5.9 | 46.01 / 5.9 |
| longform-parakeet-fp32-cpu | 19.69 / 7.0 | 45.76 / 7.9 | 13.06 / 7.5 | 39.16 / 6.1 |
| longform-parakeet-int8-cpu | 29.58 / 13.3 | 55.55 / 14.7 | 14.94 / 13.9 | 37.8 / 11.4 |
| longform-qwen3-1.7b-gpu | 20.61 / 8.4 | 46.3 / 6.5 | 15.37 / 4.8 | 41.34 / 5.0 |
| longform-ultra-fp32-gpu | 19.3 / 31.5 | 42.11 / 30.8 | 13.16 / 30.5 | 38.4 / 29.9 |
| longform-whisper-turbo-gpu | 23.03 / 50.7 | 47.66 / 44.7 | 11.23 / 38.6 | 35.54 / 37.0 |

## live

| run | WER | final latency med / p90 s | first draft med s | live CPU % mean / peak | live RSS MB | system CPU % | probe p99 / max ms | stalls >50 / >200 ms | video fps mean / min | queue RTFx | DPC % mean / peak | pages/s peak |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| live-gigaam-ctc-int8-vad-ru-t2-spin-off-normal-cpus8 | 5.92 | 0.86 / 0.96 | 1.41 | 0.8 / 6.2 | 436.0 | 5.4 | — / — | — / — | — / — | — | 0.0 / 0.3 | 10275.0 |
| live-gigaam-rnnt-window-ru-tapp-spin-on-normal-cpus8 | 5.92 | 2.82 / 3.58 | 1.37 | 4.0 / 24.9 | 1119.0 | 6.0 | — / — | — / — | — / — | — | 0.0 / 0.2 | 2362.8 |
| live-nemotron-1120-stream-en-t2-spin-off-normal-cpus8 | 17.91 | 1.08 / 1.76 | 1.96 | 0.6 / 4.3 | 837.0 | 6.2 | — / — | — / — | — / — | — | 0.0 / 0.2 | 26614.1 |
| live-nemotron-1120-stream-ru-t2-spin-off-normal-cpus8 | 15.01 | 1.09 / 1.61 | 2.07 | 0.7 / 4.1 | 837.0 | 8.0 | — / — | — / — | — / — | — | 0.0 / 0.3 | 78148.7 |
| live-nemotron-160-stream-ru-t2-spin-off-normal-cpus8 | 17.76 | 0.71 / 0.83 | 1.56 | 2.6 / 5.7 | 833.0 | 8.0 | — / — | — / — | — / — | — | 0.0 / 0.3 | 78140.5 |
| live-nemotron-560-stream-en-t2-spin-off-normal-cpus8 | 19.48 | 0.86 / 1.14 | 1.73 | 1.0 / 5.0 | 835.0 | 6.2 | — / — | — / — | — / — | — | 0.0 / 0.2 | 26614.1 |
| live-nemotron-560-stream-ru-t2-spin-off-normal-cpus8 | 15.43 | 0.89 / 1.13 | 1.76 | 0.9 / 5.0 | 834.0 | 5.4 | — / — | — / — | — / — | — | 0.0 / 0.3 | 10275.0 |
| live-parakeet-fp32-window-en-tapp-spin-on-normal-cpus8 | 4.87 | 3.18 / 4.73 | 1.72 | 6.2 / 25.7 | 2867.0 | 10.2 | — / — | — / — | — / — | — | 0.0 / 0.3 | 18268.8 |
| live-parakeet-fp32-window-ru-tapp-spin-on-normal-cpus8 | 8.46 | 2.91 / 4.02 | 1.31 | 6.1 / 25.5 | 2879.0 | 10.5 | — / — | — / — | — / — | — | 0.0 / 0.3 | 187355.3 |
| live-parakeet-int8-vad-en-t2-spin-off-normal-cpus8 | 14.26 | 0.99 / 1.22 | 1.56 | 1.0 / 6.0 | 1002.0 | 8.0 | — / — | — / — | — / — | — | 0.0 / 0.3 | 78137.7 |
| live-parakeet-int8-vad-ru-t2-spin-off-normal-cpus8 | 11.63 | 0.99 / 1.2 | 1.64 | 1.1 / 6.3 | 1082.0 | 5.4 | — / — | — / — | — / — | — | 0.0 / 0.3 | 10266.3 |
| live-parakeet-int8-window-ru-tapp-spin-off-normal-cpus8 | 12.05 | 2.75 / 3.44 | 1.38 | 1.2 / 11.9 | 1193.0 | 6.2 | — / — | — / — | — / — | — | 0.0 / 0.2 | 26691.1 |
| live-tone-stream-ru-t2-spin-off-normal-cpus8 | 16.28 | 0.76 / 0.97 | 1.83 | 0.3 / 3.6 | 410.0 | 5.4 | — / — | — / — | — / — | — | 0.0 / 0.3 | 10265.9 |
| live-ultra-int8-vad-en-t2-spin-off-normal-cpus8 | 10.96 | 0.99 / 1.25 | 1.49 | 1.0 / 6.2 | 1023.0 | 6.2 | — / — | — / — | — / — | — | 0.0 / 0.2 | 26690.6 |
| live-ultra-int8-vad-ru-t2-spin-off-normal-cpus8 | 8.46 | 0.99 / 1.19 | 1.58 | 1.1 / 6.2 | 1085.0 | 8.0 | — / — | — / — | — / — | — | 0.0 / 0.3 | 78140.9 |

## call

| run | WER | final latency med / p90 s | first draft med s | live CPU % mean / peak | live RSS MB | system CPU % | probe p99 / max ms | stalls >50 / >200 ms | video fps mean / min | queue RTFx | DPC % mean / peak | pages/s peak |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| call-gigaam-ctc-int8-vad-ru-t2-spin-off-below-q-gigaam-rnnt-int8-idle-cpus8 | 6.13 | 1.07 / 1.36 | 1.4 | 1.0 / 6.0 | 428.0 | 19.0 | 3.0 / 6.3 | 0 / 0 | 30.0 / 27.1 | 18.85 | 0.1 / 0.6 | 3768.3 |
| call-gigaam-rnnt-window-ru-tapp-spin-on-normal-q-inproc-normal-cpus8-v094 | 6.13 | 1.34 / 1.87 | 1.67 | 6.8 / 13.3 | 1247.0 | 16.6 | 2.46 / 11.0 | 0 / 0 | 30.0 / 27.8 | 10.1 | 0.1 / 0.8 | 65160.3 |
| call-nemotron-560-stream-ru-t2-spin-off-below-q-parakeet-int8-idle-cpus8 | 15.86 | 1.0 / 1.24 | 1.79 | 1.4 / 4.3 | 835.0 | 20.9 | 7.07 / 16.7 | 0 / 0 | 30.0 / 26.5 | 13.85 | 0.2 / 1.1 | 9386.7 |
| call-parakeet-fp32-window-en-tapp-spin-on-normal-cpus8-v094 | 8.0 | 4.28 / 6.4 | 0.9 | 3.5 / 6.3 | 2921.0 | 13.4 | 6.03 / 7.7 | 0 / 0 | 30.0 / 27.2 | — | 0.1 / 0.7 | 45171.0 |
| call-parakeet-fp32-window-en-tapp-spin-on-normal-q-inproc-normal-cpus8-v094-live4 | 5.57 | 3.24 / 5.54 | 1.23 | 8.1 / 17.7 | 6047.0 | 18.4 | 6.16 / 10.5 | 0 / 0 | 30.0 / 26.9 | 2.48 | 0.1 / 0.7 | 48164.8 |
| call-parakeet-fp32-window-en-tapp-spin-on-normal-q-inproc-normal-cpus8-v094 | 9.04 | 4.19 / 7.5 | 1.79 | 10.8 / 16.8 | 5971.0 | 22.2 | 6.9 / 13.4 | 0 / 0 | 30.0 / 27.0 | 3.84 | 0.2 / 0.6 | 153275.4 |
| call-parakeet-fp32-window-ru-tapp-spin-off-normal-q-inproc-normal-cpus8 | 8.67 | 4.0 / 5.2 | 1.62 | 15.7 / 21.5 | 4281.0 | 24.6 | 4.45 / 6.9 | 0 / 0 | 30.0 / 27.1 | 4.68 | 0.1 / 0.5 | 172488.5 |
| call-parakeet-fp32-window-ru-tapp-spin-on-normal-cpus8 | 8.46 | 3.15 / 4.71 | 1.57 | 6.3 / 21.9 | 2858.0 | 14.4 | 37.55 / 101.1 | 110 / 0 | 30.0 / 26.2 | — | 0.0 / 0.4 | 1726.8 |
| call-parakeet-fp32-window-ru-tapp-spin-on-normal-q-inproc-normal-cpus8 | 8.88 | 4.37 / 7.65 | 1.4 | 18.3 / 22.3 | 4816.0 | 26.8 | 72.25 / 108.5 | 645 / 0 | 30.0 / 25.1 | 3.08 | 0.1 / 0.4 | 17474.1 |
| call-parakeet-fp32-window-ru-tapp-spin-on-normal-q-inproc-normal | 8.46 | 3.26 / 3.81 | 1.45 | 25.8 / 46.3 | 4434.0 | 35.1 | 0.76 / 4.2 | 0 / 0 | 30.0 / 27.8 | 12.28 | 0.1 / 0.5 | 18011.1 |
| call-parakeet-int8-vad-ru-t2-spin-off-below-q-parakeet-int8-idle-cpus8 | 11.63 | 1.57 / 2.11 | 1.48 | 1.4 / 5.8 | 1033.0 | 21.9 | 7.39 / 16.8 | 0 / 0 | 30.0 / 27.0 | 12.94 | 0.2 / 1.3 | 42031.2 |
| call-parakeet-int8-vad-ru-tapp-spin-off-normal-q-parakeet-int8-normal-cpus8 | 11.42 | 1.24 / 1.56 | 1.67 | 1.8 / 11.3 | 1043.0 | 27.2 | 14.05 / 30.6 | 0 / 0 | 30.0 / 25.9 | 16.16 | 0.2 / 1.0 | 74733.9 |
| call-parakeet-int8-vad-ru-tapp-spin-on-normal-q-parakeet-int8-normal-cpus8 | 11.42 | 2.93 / 4.4 | 1.45 | 5.9 / 17.1 | 1039.0 | 28.3 | 86.35 / 198.5 | 1386 / 0 | 30.0 / 21.5 | 9.61 | 0.1 / 0.7 | 48463.2 |
| call-parakeet-int8-window-ru-tapp-spin-off-normal-q-inproc-normal-cpus8 | 10.99 | 3.04 / 3.81 | 1.21 | 9.4 / 17.9 | 3085.0 | 17.6 | 7.73 / 32.4 | 0 / 0 | 30.0 / 26.3 | 8.87 | 0.1 / 0.5 | 5013.4 |
| call-tone-stream-ru-t2-spin-off-below-q-gigaam-rnnt-int8-idle-cpus8 | 16.28 | 0.77 / 0.98 | 1.75 | 0.4 / 2.6 | 411.0 | 18.2 | 2.79 / 6.9 | 0 / 0 | 30.0 / 27.6 | 20.89 | 0.1 / 0.4 | 20519.9 |

## idle (no recognition)

| run | probe p99 / max ms | stalls >50 / >200 | video fps mean / min | system CPU % |
|---|---|---|---|---|
| idle-cpus8 | 0.59 / 1.2 | 0 / 0 | — / — | 1.9 |
| idle-video-cpus8 | 6.04 / 6.8 | 0 / 0 | 30.0 / 28.3 | 7.6 |
| idle-video | 0.6 / 1.2 | 0 / 0 | 30.0 / 28.3 | 5.5 |


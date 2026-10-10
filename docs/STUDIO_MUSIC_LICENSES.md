# Studio Music — dependencies and references (33.3.27)

The engine and interface are original ZAR code using browser Web Audio,
OfflineAudioContext, Canvas and MediaRecorder. No new runtime package or external
sample collection is incorporated. Tone.js remains a possible future adapter;
native Web Audio avoids an additional runtime and integrates with the existing Studio.

References reviewed through their official repositories; no code/assets copied:

| Repository | Published licensing signal | Use |
|---|---|---|
| Tonejs/Tone.js | MIT in package metadata | Audio scheduling reference |
| dvir-drori/daw | README states MIT; no standalone LICENSE observed | Concept only |
| XanthanL/neon-daw | MIT license listed | Module organization concept |
| naomiaro/waveform-playlist | MIT package metadata | Waveform/editing concept |
| yusei-h/web-daw | MIT | Workspace concept |
| TarasMoskovych/tone-sketch | README states MIT | Piano roll concept |
| KGAudioLab/K.G.Studio | Apache 2.0 plus additional terms | Concept only; not reused |
| AppsYogi-com/ComposeYogi | MIT | Arrangement concept |
| onurravli/flottant | No license verified | Not reused |

Initial piano/pad/bass/drums are synthesized, not sampled. User-imported audio
remains the user's responsibility. MIDI export is original standard-file encoding.

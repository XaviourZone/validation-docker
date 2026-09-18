# iTrackLib 41-field audit

Source: uploaded authoritative iTrackLib wrapper, Pasted text(10).txt (1184 lines).

This matrix records the direct dotted XML-field branches currently found by searching for saisDataId == ... . A missing branch does not prove the XML field is invalid; it means the supplied wrapper does not contain a direct handler for that dotted ID.

| # | XML field | iTrackLib direct branch | Line | Classification |
|---:|---|---|---:|---|
| 1 | ais.lenToBow | yes | 413 | directly consumed |
| 2 | ais.lenToStern | yes | 421 | directly consumed |
| 3 | ais.navStatus | yes | 436 | directly consumed |
| 4 | ais.typeAndCargo | yes | 478 | directly consumed |
| 5 | ais.widthToPort | yes | 1165 | directly consumed |
| 6 | ais.widthToStarboard | yes | 1173 | directly consumed |
| 7 | app.message.id | no | — | no direct dotted branch |
| 8 | cat.annotation | no | — | no direct dotted branch |
| 9 | cat.category | yes | 961 | directly consumed |
| 10 | cat.identity | yes | 978 | directly consumed |
| 11 | foreign.track.number | no | — | no direct dotted branch |
| 12 | id.callsign | yes | 305 | directly consumed |
| 13 | id.imo | yes | 316 | directly consumed |
| 14 | id.mmsi | yes | 323 | directly consumed |
| 15 | id.mmsi.destination | yes | 1156 | directly consumed |
| 16 | kinematic.course.true | yes | 279 | directly consumed |
| 17 | kinematic.flag.3d | no | — | no direct dotted branch |
| 18 | kinematic.heading.true | yes | 286 | directly consumed |
| 19 | kinematic.pos.lla.alt | yes | 299 | directly consumed |
| 20 | kinematic.pos.lla.lat | yes | 264 | directly consumed |
| 21 | kinematic.pos.lla.lon | yes | 272 | directly consumed |
| 22 | kinematic.speed | yes | 293 | directly consumed |
| 23 | sys.source.id | yes | 257 | directly consumed |
| 24 | sys.track.number | no | — | no direct dotted branch |
| 25 | timestamp.receipt | yes | 353 | directly consumed |
| 26 | timestamp.source | yes | 330 | directly consumed |
| 27 | track.flag.active | yes, but no active setter | 945 | branch exists; value is not forwarded to C library |
| 28 | track.quality | yes | 953 | directly consumed |
| 29 | vessel.beam | no | — | no direct dotted branch |
| 30 | vessel.description | yes | 1099 | directly consumed |
| 31 | vessel.draft | no | — | no direct dotted branch |
| 32 | vessel.grosstonnage | yes | 1140 | directly consumed |
| 33 | vessel.length | yes | 385 | directly consumed |
| 34 | vessel.name | yes | 393 | directly consumed |
| 35 | vessel.remarks | yes | 1112 | directly consumed |
| 36 | voyage.arrival | yes | 1075 | directly consumed |
| 37 | voyage.departure | no | — | no direct dotted branch; wrapper has separate voyage_departure handling |
| 38 | voyage.destination | yes | 926 | directly consumed |
| 39 | voyage.eta | yes | 1001 | directly consumed |
| 40 | voyage.etd | yes | 1025 | directly consumed |
| 41 | voyage.origin | yes | 1049 | directly consumed |

## Count

- Canonical XML fields: 41
- Canonical fields with a direct `saisDataId` branch: 33
- Canonical fields with no direct dotted branch: 8
- Of those 33 branches, `track.flag.active` has no active C-library setter; its apparent setter is commented out.

## Exact downstream observations

- sys.source.id is converted to an integer and passed to the sensor-type setter.
- Latitude/longitude are read as radians and converted by the wrapper to degrees/minutes scaled by 10000 before the C setter.
- Course and heading are read as radians and converted to degrees scaled by 10000. The supplied wrapper calls the same course setter for both branches; this is an observed implementation fact.
- Speed is read as m/s and the wrapper divides by 0.001 before the C setter.
- id.callsign is explicitly commented with maximum length 11 in the supplied wrapper.
- timestamp.source is divided by 1000 before datetime conversion, so the XML contract is epoch milliseconds.
- ais.navStatus is a textual XML field in the supplied sample and is converted to a numeric navigation-status code by the wrapper.
- ais.typeAndCargo is a textual XML field and the wrapper maps a large vocabulary to ship-type / track-class numeric values.
- cat.identity is a textual classification in the supplied XML sample (for example Friend / Neutral / Suspect), while the wrapper maps it to its internal code.
- voyage.destination is stripped/mapped through the downstream destination dictionary and sent to destination setters.
- The wrapper contains additional XML IDs outside this 41-field contract. They are not silently added to the canonical contract.

## Max-length rule

Only the callsign maximum length is explicitly visible in the supplied wrapper (MAX Length 11). Maximum lengths for the other string fields are not established by this source and must not be guessed. The final mapping matrix should mark them as unknown/not enforced until the actual downstream implementation or master schema establishes them.

# The three-minute walk

One line per still.
Each line names the panel on screen as `(on screen: pNN)`, and `demo/STILLS/` holds one picture per line, named `NN-pNN-<panel>.png`.
Read at an easy pace, each line takes about fifteen seconds; thirteen lines make a little over three minutes.

1. I built faultline, a rules judge for video: a site gives it its rules in plain words and its camera footage, and it gives back rulings, each with the rule, the frames and the number that decided it. (on screen: p01, the title)
2. This is the rules pack exactly as the site wrote it, one rule to a file: hi-vis in the truck zone, a spotter when reversing, distance from people on foot, and no touching the racking. (on screen: p02, the rules pack)
3. Every rule gets one of three answers: a breach, a clear, or unable to rule, and I never let it guess, so when a fact was not measured, the ruling says which fact. (on screen: p03, the three verdicts)
4. Here is a breach: a person walks along the racking near a working truck, and these are the frames the ruling names, taken straight from the clip. (on screen: p04, the breach frames)
5. The ruling shows the number that decided it: no hi-vis band on the torso on every frame it could read, against the site's line, with the record hash underneath. (on screen: p05, the breach ruling)
6. A model looked at the same frames and wrote these words; I show them once, as words beside the ruling, never the ruling, because the measurement decides and the words only help a person check. (on screen: p06, the words beside the ruling)
7. Here is a clear: two people ahead of the truck, both in vests on every frame, and the other three rules on this clip come back clear as well. (on screen: p07, the clear)
8. And here is the honest one: a group in vests crosses in front of the truck, but the bottom of the frame cuts the truck off, so you never see where it meets the floor. (on screen: p08, the unable frames)
9. So it does not guess whether the truck was moving: it rules unable, names that one missing fact, and shows the measurement that left it open. (on screen: p09, the unable ruling)
10. On a real site this runs over a whole shift, an hour or more of footage from each camera: it cuts the footage into windows, measures every window on every rule, and surfaces everything that registers as an incident, with its frames and its number, for a person to review; the most common reason for unable is a camera that moved, because this judge reads fixed site cameras. (on screen: p10, the shift)
11. Every ruling rebuilds from its own record with the network off and no footage, and the rebuilt file has the same hash as the original, byte for byte. (on screen: p11, the replay proof)
12. To do better on a real site it needs three things from the site, not from a model: the camera's height and lens, so the metre is exact instead of marked by hand; the truck's clearance, so the floor fix I measured on a synthetic twin switches on; and a second camera on the racking, because a touch with no visible consequence cannot be seen from one angle, and the judge says so rather than guess. (on screen: p12, the close)
13. That is faultline: rules in, rulings out, a number behind every breach, and an honest "I can't tell" that names exactly what it could not see. (on screen: p12, the close)

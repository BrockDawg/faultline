# The three-minute walk

One line per still.
Each line names the panel on screen as `(on screen: pNN)`, and `demo/STILLS/` holds one picture per line, named `NN-pNN-<panel>.png`.
Read at an easy pace, each line takes about thirteen seconds; thirteen lines make just under three minutes.

1. I built faultline, a rules judge for video. A site gives it its rules in plain words and its camera footage, and it gives back rulings: the rule, the frames, and the number that decided it. (on screen: p01, the title)
2. This is the rules pack, exactly as the site wrote it, one rule to a file: hi-vis in the truck zone, a spotter when reversing, distance from people on foot, and no touching the racking. (on screen: p02, the rules pack)
3. Every rule gets one of three answers: breach, clear, or unable to rule. It never guesses. When a fact was not measured, the ruling names that fact. (on screen: p03, the three verdicts)
4. Here is a breach. A person walks along the racking near a working truck. SAM 3.1 tracked the truck and found the person, and these are the frames the ruling names. (on screen: p04, the breach frames)
5. The ruling shows the number that decided it: no hi-vis band on the torso on every frame it could read, against the site's line, with the record hash underneath. (on screen: p05, the breach ruling)
6. Meta's Muse Wonder wrote these words from the same frames, and Muse Spark Open read the rule three times. They sit beside the ruling, never the ruling, so a person can check faster. (on screen: p06, the words beside the ruling)
7. Here is a clear: two people ahead of the truck, both in vests on every frame, by the script's colour read and by Wonder's three reads. The other three rules come back clear too. (on screen: p07, the clear)
8. And the honest one. A group in vests crosses in front of the truck, but the frame cuts the truck off, so you never see where it meets the floor. (on screen: p08, the unable frames)
9. So it does not guess whether the truck was moving. It rules unable, names that one missing fact, and shows the measurement that left it open. (on screen: p09, the unable ruling)
10. On a real site this runs over a whole shift, an hour or more per camera, every rule on every window, and every incident goes to a person with its frames and its number. On the demo shift, 48 windows, that meant 16 incidents, 84 clears and 140 unable, most because the camera moved. (on screen: p10, the shift)
11. Every ruling rebuilds from its own record with the network off and no footage, and the rebuilt file has the same hash, byte for byte. Three clips' records ship in the repo, so you can run it yourself. (on screen: p11, the replay proof)
12. Three things from the site, not from a model, make it better: the camera's height and lens, the truck's clearance, and a better camera on the racking, or more than one, because a touch with no visible consequence cannot be seen from one angle. (on screen: p12, the close)
13. That is faultline: rules in, rulings out, a number behind every breach, and an honest "I can't tell" that names what it could not see. Built for the safety lead and the insurer, and for the race stewards in my own leagues. (on screen: p12, the close)

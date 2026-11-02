# The three-minute walk

One line per segment, spoken the way I would say it to a friend.
Each line names the panel on screen as `(on screen: pNN)`, and `demo/STILLS/` holds one picture per line, named `NN-pNN-<panel>.png`.
Sixteen lines, about three minutes at an easy pace.

1. Hi, I'm Brock. I run PitBot, a platform for sim-racing leagues. When a driver protests a move, a volunteer steward, the person who rules on protests, digs through race footage to decide. faultline does the digging. (on screen: p01, the title)
2. Here's racing. A driver protests a lap. I've got the broadcast video and the telemetry, the data the sim records for every car, lined up to within about two seconds. (on screen: p14, the racing panel)
3. The steward names the moment, and faultline cuts frames there, half a second apart, with the cars boxed and the data's facts beside them: which cars were close, and when. The steward still makes the call. (on screen: p14, the racing panel)
4. Then I tried the place where this really matters: a warehouse, which I'll call a site. Forklifts hurt people, insurers want proof a site follows its own rules, and nobody can watch every camera. The site writes its rules in plain English, one per file, like wear a vest near the trucks. (on screen: p02, the rules pack)
5. Every rule on every clip gets one of three answers. Breach, it was broken. Clear, it wasn't. Or unable, it couldn't tell, and it names the fact it was missing. It never guesses. (on screen: p03, the three verdicts)
6. Here's one. A man walks along the racks near a working forklift. Meta's SAM 3.1 model finds the truck and the people in every frame. (on screen: p04, the breach frames)
7. The rule says wear a hi-vis vest. A script, plain code, checks the colour on him. It read 22 frames, and the site wants a vest in 70 percent. He has none. Breach. (on screen: p05, the breach ruling)
8. Meta's language models help a person check. Muse Spark Open, an open model I run on Baseten, reads the rule from the frames three times. Muse Wonder writes two sentences. Neither changes the verdict. (on screen: p06, the words beside the ruling)
9. The opposite: two people ahead of the truck, both in vests, every frame. Clear. Wonder only gets asked about a vest when the colour check isn't sure. (on screen: p07, the clear)
10. This one's why I trust it. A group crosses in front of the truck, but the camera cuts the truck off at the bottom of the frame. You can't see where it meets the floor. (on screen: p08, the unable frames)
11. So nobody can tell whether the truck was moving. faultline doesn't pretend. It says unable, and names the one thing it couldn't see. (on screen: p09, the unable ruling)
12. Nobody watches a whole shift, so it checks every rule in each five-second window and hands the safety lead a short list. My test shift: 48 windows, sixteen to review, 84 clear, 140 unable, mostly because the camera moved. (on screen: p10, the shift)
13. Every ruling writes a record, a file of what it measured. Turn the network off, delete the footage, rebuild it, and you get the same bytes. Three records ship with the code, so check me. (on screen: p11, the replay proof)
14. This week, real warehouse footage: five free clips, one still camera. Three it refused: the camera moved. On the still one it saw a touch that never happened, because the camera sat near the floor. Now it refuses cameras under 1.5 metres. (on screen: p13, the real footage)
15. To do better it needs three things from the site: the camera's height and lens, the truck's clearance, and a second camera on the racks. One angle can't show everything. (on screen: p12, the close)
16. That's faultline. The site writes the rules, scripts measure and decide, Meta's models add words, and a person makes the call. A site gets proof it follows its rules, an insurer gets evidence instead of a form, and my stewards get their evenings back. Thanks for watching. (on screen: p12, the close)

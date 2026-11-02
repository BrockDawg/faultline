# The three-minute walk

One line per segment, spoken the way I would say it to a friend.
Each line names the panel on screen as `(on screen: pNN)`, and `demo/STILLS/` holds one picture per line, named `NN-pNN-<panel>.png`.
Sixteen lines, about three minutes at an easy pace.

1. Every warehouse has cameras, and nobody watches them. When a forklift clips a rack or nearly hits someone, somebody has to find the footage and then argue about the rule. My sim-racing stewards have the same job with race footage. So I built faultline: it finds the moment, measures what happened, and leaves the ruling to a person. (on screen: p01, the title)
2. This is where it started: my own leagues. A driver protests a lap and names the moment. This is the broadcast, and this is the car telemetry, lined up to the half second. (on screen: p14, the racing panel)
3. faultline cuts the frames at that moment, marks every car in view, and lays the feed's facts beside them: who was where, how close, for how long. The steward still rules, but from evidence, not memory. (on screen: p14, the racing panel)
4. Now the same judge in a warehouse. You give it two things: the rules in plain English, the way the warehouse already writes them, like wear a vest near the trucks or don't hit the racks, and the camera footage. (on screen: p02, the rules pack)
5. For every rule, on every clip, one of three answers: broken, fine, or "I can't tell". That last one is the point. It never guesses. (on screen: p03, the three verdicts)
6. Watch one clip. A man walks along the racks with a forklift working beside him. Meta's SAM 3.1 finds the truck and the person in every frame. These are the frames the ruling points at. (on screen: p04, the breach frames)
7. The rule says wear a vest. The colour check finds no vest on him in all 22 frames it could read, against the site's line of 70 percent. Broken. Under the number, a hash of the whole record. Remember that. (on screen: p05, the breach ruling)
8. Two Meta models look at the same frames: Muse Wonder writes two sentences, and Muse Spark Open reads the rule three times. Their words sit beside the ruling so a person checks faster. They never make the call. (on screen: p06, the words beside the ruling)
9. Here's the opposite: two people ahead of the truck, both in vests, every frame. Fine. Wonder is only asked when the colour check isn't sure. (on screen: p07, the clear)
10. Now here's why I trust it. A group crosses in front of the truck, but the camera cuts the truck off at the bottom. You cannot see where it meets the floor. (on screen: p08, the unable frames)
11. So nobody knows if it was moving. It says "I can't tell" and names the one thing it couldn't see. (on screen: p09, the unable ruling)
12. On a real site this runs on a whole shift, every rule every five seconds, and a person gets a short list. My test shift: forty-eight windows, sixteen worth a look, eighty-four fine, a hundred and forty "can't tell", mostly a moving camera. (on screen: p10, the shift)
13. That hash? Every ruling writes a record. Turn the network off, delete the footage, run it again: the exact same bytes. Three records ship in the repo, so you can check me. (on screen: p11, the replay proof)
14. This week, real warehouse footage for the first time: five free clips, one still camera. Three it refused, the camera moved. On the still one it got something wrong, a touch that never happened, because the camera sat on the floor. Now it refuses a camera that low. (on screen: p13, the real footage)
15. To do better it needs three things from the site, not a model: the camera's height and lens, the truck's ground clearance, and a second camera on the racks. Some things you can't see from one angle. (on screen: p12, the close)
16. That's faultline. Rules in, rulings out, a number behind every breach, and an honest "I can't tell". For my stewards, and for every site with a camera nobody watches. Thanks for watching. (on screen: p12, the close)

"""The PitBot adapter: companion replay feeds, protest exports and league configs for sim racing.

Cars are named by their sim number only. Driver names are read into memory to normalise
protest text and are never written to a file, a log or a prompt.

`DOMAIN` is the word `faultline` answers to for this adapter's commands, and `CLI` the module
(relative to this package) whose `register(parser)` adds them; see `faultline.cli`.
"""

DOMAIN = "racing"
CLI = ".cli"

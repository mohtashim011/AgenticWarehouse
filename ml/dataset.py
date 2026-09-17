"""
Training data
=============
Labelled product names for the category classifier.

The original MVP trained on 20 samples and scored 70% under leave-one-out
cross-validation. That is not a model problem — it is a data problem. Twenty
examples across three categories gives each class barely six, so a single
unusual word swings the whole posterior.

This set covers the two product families this warehouse actually handles:

* the **telecom** stock from the AUTOWARE project (ONT, IPTV, cables, remotes)
* the **homeware** stock currently on the shelves (glassware, mugs, plasticware)

Names are written the way suppliers really write them — inconsistent casing,
sizes appended, abbreviations, brand-free. The deliberate overlaps (a "beer mug"
that is glassware, a "jug" that could be either glass or plastic) are not
mistakes: they are the genuinely hard cases, and they belong in the training set
so the confusion matrix reports an honest picture instead of a flattering one.
"""

import db

# ---------------------------------------------------------------------------
# The labelled corpus
# ---------------------------------------------------------------------------
TRAINING = [
    # -- Networking ---------------------------------------------------------
    ("ONT optical network terminal", "Networking"),
    ("ONT device fiber", "Networking"),
    ("ONT gpon terminal white", "Networking"),
    ("gpon ont router combo", "Networking"),
    ("optical fiber cable", "Networking"),
    ("fiber optic patch cable 2m", "Networking"),
    ("single mode fiber patch cord", "Networking"),
    ("fibre drop cable 100m drum", "Networking"),
    ("ethernet cable rj45 cat6", "Networking"),
    ("cat5e utp patch lead grey", "Networking"),
    ("cat6a shielded network cable", "Networking"),
    ("lan network cable 5m", "Networking"),
    ("rj45 connector crimp plug", "Networking"),
    ("wifi router dual band ac1200", "Networking"),
    ("wireless router 4 antenna", "Networking"),
    ("mesh wifi access point", "Networking"),
    ("ceiling wireless access point poe", "Networking"),
    ("network switch gigabit 8 port", "Networking"),
    ("managed switch 24 port rack", "Networking"),
    ("poe injector gigabit", "Networking"),
    ("modem broadband adsl", "Networking"),
    ("vdsl modem router", "Networking"),
    ("sfp transceiver module 1g", "Networking"),
    ("patch panel 24 port cat6", "Networking"),
    ("network rack cabinet 9u", "Networking"),
    ("fiber splice closure", "Networking"),
    ("optical splitter 1x8 plc", "Networking"),
    ("media converter fiber ethernet", "Networking"),
    ("ip camera poe outdoor", "Networking"),
    ("network cable tester tool", "Networking"),

    # -- Entertainment ------------------------------------------------------
    ("iptv device streaming box", "Entertainment"),
    ("iptv set top box hd", "Entertainment"),
    ("set top box decoder satellite", "Entertainment"),
    ("android tv box media player", "Entertainment"),
    ("android tv streaming stick 4k", "Entertainment"),
    ("smart tv dongle hdmi", "Entertainment"),
    ("universal remote control", "Entertainment"),
    ("tv remote controller replacement", "Entertainment"),
    ("bluetooth voice remote", "Entertainment"),
    ("decoder remote control black", "Entertainment"),
    ("satellite dish lnb universal", "Entertainment"),
    ("dvb t2 receiver tuner", "Entertainment"),
    ("media player hard drive 1080p", "Entertainment"),
    ("soundbar speaker bluetooth", "Entertainment"),
    ("home theatre speaker set", "Entertainment"),
    ("portable bluetooth speaker", "Entertainment"),
    ("projector hdmi 1080p portable", "Entertainment"),
    ("projector screen tripod", "Entertainment"),
    ("game controller wireless pad", "Entertainment"),
    ("headphones over ear wired", "Entertainment"),
    ("earphones in ear bud", "Entertainment"),
    ("tv wall mount swivel", "Entertainment"),
    ("digital signage player box", "Entertainment"),
    ("radio fm portable speaker", "Entertainment"),
    ("streaming subscription card voucher", "Entertainment"),

    # -- Accessories --------------------------------------------------------
    ("hdmi cable 4k 2m", "Accessories"),
    ("hdmi cable high speed gold", "Accessories"),
    ("power adapter charger 12v", "Accessories"),
    ("power supply unit 5v 2a", "Accessories"),
    ("universal travel adapter plug", "Accessories"),
    ("extension cord 3 way surge", "Accessories"),
    ("multiplug adaptor 4 socket", "Accessories"),
    ("mounting bracket screws set", "Accessories"),
    ("wall mount bracket steel", "Accessories"),
    ("cable ties clips 100 pack", "Accessories"),
    ("cable trunking pvc 2m", "Accessories"),
    ("velcro cable wrap roll", "Accessories"),
    ("usb cable connector type c", "Accessories"),
    ("usb a to micro usb lead", "Accessories"),
    ("usb hub 4 port powered", "Accessories"),
    ("battery aa alkaline 4 pack", "Accessories"),
    ("battery aaa rechargeable", "Accessories"),
    ("screwdriver set precision", "Accessories"),
    ("cable clips nail in white", "Accessories"),
    ("rj45 keystone jack module", "Accessories"),
    ("memory card sd 32gb", "Accessories"),
    ("usb flash drive 64gb", "Accessories"),
    ("laptop charger 65w", "Accessories"),
    ("phone charger fast 20w", "Accessories"),
    ("aux audio cable 3.5mm", "Accessories"),

    # -- Glassware ----------------------------------------------------------
    ("martini glass 225ml", "Glassware"),
    ("martini cocktail glass set", "Glassware"),
    ("wine glass 350ml stemmed", "Glassware"),
    ("red wine glass crystal", "Glassware"),
    ("white wine glass tall stem", "Glassware"),
    ("champagne flute 180ml", "Glassware"),
    ("champagne coupe glass", "Glassware"),
    ("whisky tumbler glass 300ml", "Glassware"),
    ("water tumbler glass clear", "Glassware"),
    ("highball glass 400ml", "Glassware"),
    ("shot glass 50ml set of 6", "Glassware"),
    ("beer mug glass 500ml handle", "Glassware"),
    ("beer pint glass tempered", "Glassware"),
    ("glass jug 1500ml handle", "Glassware"),
    ("glass decanter whisky 750ml", "Glassware"),
    ("glass pitcher water clear", "Glassware"),
    ("brandy snifter glass", "Glassware"),
    ("cocktail coupe glass 200ml", "Glassware"),
    ("glass bowl serving 2000ml", "Glassware"),
    ("glass storage jar lid 1000ml", "Glassware"),
    ("drinking glass tumbler 6 pack", "Glassware"),
    ("juice glass small 200ml", "Glassware"),
    ("glass teacup saucer clear", "Glassware"),
    ("glass water bottle 750ml", "Glassware"),
    ("glass salad bowl large", "Glassware"),

    # -- Coffee Mugs --------------------------------------------------------
    ("coffee mug ceramic 350ml", "Coffee Mugs"),
    ("coffee mug white porcelain", "Coffee Mugs"),
    ("ceramic mug printed logo", "Coffee Mugs"),
    ("porcelain mug 300ml handle", "Coffee Mugs"),
    ("stoneware coffee mug matte", "Coffee Mugs"),
    ("travel mug stainless steel lid", "Coffee Mugs"),
    ("thermal mug vacuum insulated", "Coffee Mugs"),
    ("insulated coffee tumbler lid", "Coffee Mugs"),
    ("espresso cup 80ml ceramic", "Coffee Mugs"),
    ("cappuccino cup and saucer", "Coffee Mugs"),
    ("latte mug tall ceramic", "Coffee Mugs"),
    ("tea mug ceramic 400ml", "Coffee Mugs"),
    ("bone china mug floral", "Coffee Mugs"),
    ("enamel camping mug", "Coffee Mugs"),
    ("double wall coffee mug", "Coffee Mugs"),
    ("mug set of 4 assorted", "Coffee Mugs"),
    ("souvenir mug printed", "Coffee Mugs"),
    ("breakfast mug jumbo 500ml", "Coffee Mugs"),
    ("coffee cup ceramic stackable", "Coffee Mugs"),
    ("mug tree stand wooden", "Coffee Mugs"),

    # -- Plasticware --------------------------------------------------------
    ("water bottle 1000ml plastic", "Plasticware"),
    ("water bottle 500ml sports cap", "Plasticware"),
    ("plastic storage container 4500ml", "Plasticware"),
    ("food storage container set lids", "Plasticware"),
    ("plastic lunch box compartment", "Plasticware"),
    ("plastic bucket 10l handle", "Plasticware"),
    ("plastic jug 2000ml measuring", "Plasticware"),
    ("plastic basin round 5l", "Plasticware"),
    ("plastic tray serving rectangular", "Plasticware"),
    ("plastic crate stackable 20l", "Plasticware"),
    ("plastic bin with lid 25l", "Plasticware"),
    ("plastic cutlery set disposable", "Plasticware"),
    ("plastic plate set of 6", "Plasticware"),
    ("plastic bowl mixing 3000ml", "Plasticware"),
    ("plastic cup 250ml reusable", "Plasticware"),
    ("plastic funnel kitchen", "Plasticware"),
    ("plastic chopping board", "Plasticware"),
    ("plastic laundry basket", "Plasticware"),
    ("plastic drawer organiser", "Plasticware"),
    ("plastic dustbin pedal 12l", "Plasticware"),
    ("tupperware container round", "Plasticware"),
    ("plastic ice tray mould", "Plasticware"),
    ("plastic watering can 5l", "Plasticware"),
    ("plastic hanger set of 10", "Plasticware"),
    ("plastic spray bottle 750ml", "Plasticware"),
]


def base_dataset():
    """The built-in labelled corpus."""
    return list(TRAINING)


def learned_dataset():
    """What the user has taught the system through the catalogue.

    Every product a manager files under a category is a labelled example, given
    by the person who actually knows. Folding those back in is what makes the
    classifier improve with use rather than staying frozen at whatever was
    shipped.
    """
    out = []
    for row in db.catalog_rows():
        name = (row.get("name") or "").strip()
        category = (row.get("category") or "").strip()
        if not name or not category or category == db.UNCATEGORISED:
            continue
        out.append((name, category))
    return out


def full_dataset(include_learned=True):
    """The corpus the models actually train on.

    User-assigned labels win over built-in ones for the same product name: if a
    manager has filed something, that is the ground truth by definition.
    """
    combined = {}
    for text, label in base_dataset():
        combined[text.lower()] = (text, label, "built-in")
    if include_learned:
        for text, label in learned_dataset():
            combined[text.lower()] = (text, label, "learned")
    return [(t, l) for t, l, _ in combined.values()]


def dataset_stats(include_learned=True):
    """Where the training data comes from, and how it is balanced.

    Class balance is reported because it is the single number that most often
    explains a disappointing accuracy score, and it is the first thing anyone
    reading the report should be able to check.
    """
    data = full_dataset(include_learned)
    per_class = {}
    for _, label in data:
        per_class[label] = per_class.get(label, 0) + 1
    learned = len(learned_dataset()) if include_learned else 0
    counts = sorted(per_class.values())
    return {
        "total": len(data),
        "classes": len(per_class),
        "per_class": dict(sorted(per_class.items())),
        "built_in": len(base_dataset()),
        "learned": learned,
        "smallest_class": counts[0] if counts else 0,
        "largest_class": counts[-1] if counts else 0,
        # 1.0 is perfectly balanced. Below ~0.5 the majority classes start to
        # dominate and per-class recall is the number to watch, not accuracy.
        "balance": round(counts[0] / counts[-1], 3) if counts and counts[-1] else 0.0,
    }

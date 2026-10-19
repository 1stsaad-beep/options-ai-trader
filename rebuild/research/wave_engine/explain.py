"""Evidence for / against a scenario in plain Arabic (top contributions of its score)."""
from __future__ import annotations
from . import patterns as PT

AR = {
    "w2_fib": "الموجة 2 صححت بنسبة فيبوناتشي معتادة",
    "w3_ext": "الموجة 3 = امتداد فيبوناتشي للموجة 1",
    "w4_fib": "الموجة 4 صححت بنسبة فيبوناتشي معتادة",
    "w5_eq1": "الموجة 5 تساوي الموجة 1 أو 0.618 من (0→3)",
    "has_extension": "إحدى الموجات الدافعة ممتدة بوضوح",
    "alternation": "تناوب واضح بين الموجتين 2 و4",
    "sub_motive": "الموجات الدافعة مقسمة داخلياً إلى 5",
    "sub_corr": "الموجات التصحيحية مقسمة داخلياً إلى 3",
    "bottom_up": "البنية الداخلية للموجات (5 أو 3) تطابق الترقيم",
    "truncated5": "الموجة 5 مبتورة (لم تتجاوز قمة 3)",
    "b_fib": "B صححت نسبة فيبوناتشي من A",
    "c_eq_a": "C تساوي A أو بنسبة فيبوناتشي منها",
    "c_fib": "C بنسبة فيبوناتشي من A",
    "running": "فلات جاري (C لم تصل نهاية A)",
    "tri_fib": "أضلاع المثلث بنسب فيبوناتشي",
    "tri_contracting": "مثلث منكمش منتظم",
    "prop": "تناسب أحجام وأزمنة الموجات",
    "open_prop": "الموجة الجارية ضمن الحجم والزمن المعتاد",
    "open_time": "الموجة التصحيحية الجارية لم تطل زمنياً أكثر من المعتاد",
    "diag_contracting": "قطري منكمش",
}
AR_NEG = {
    "prop": "عدم تناسب: موجة تصحيحية صغيرة جداً أو مدد زمنية غير متناسبة",
    "open_prop": "الموجة الجارية أطول بكثير من المعتاد سعراً أو زمناً",
    "open_time": "الموجة التصحيحية الجارية طالت زمنياً أكثر من المعتاد",
    "sub_motive": "موجة يُفترض أنها دافعة لكن بنيتها الداخلية 3",
    "sub_corr": "موجة يُفترض أنها تصحيحية لكن بنيتها الداخلية 5",
    "bottom_up": "البنية الداخلية للموجات تعارض الترقيم",
    "truncated5": "يحتاج الترقيم موجة 5 مبتورة (نادرة)",
    "running": "يحتاج فلاتاً جارياً (نادر)",
}


def evidence(z, k=3):
    contrib = []
    for key, v in z.feats.items():
        base = key[2:] if key.startswith("2_") else key
        w = PT.W.get(base, 0.0)
        c = w * (v - PT.FIB_BASE) if base in PT.FIBKEYS else w * v
        if abs(c) < 0.05: continue
        txt = (AR.get(base) if c > 0 else AR_NEG.get(base, "ضعف: " + AR.get(base, base)))
        if txt: contrib.append((c, txt))
    if getattr(z, "irr", 0):
        contrib.append((-0.4 * z.irr, "نهاية موجة ليست أعلى/أدنى سعر (قمة أرثوذكسية مختلفة)"))
    pos = [t for c, t in sorted(contrib, reverse=True) if c > 0][:k]
    neg = [t for c, t in sorted(contrib) if c < 0][:k]
    return pos, neg

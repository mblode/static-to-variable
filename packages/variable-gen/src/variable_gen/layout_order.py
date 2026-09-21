"""Canonical OpenType feature order with all referring indexes preserved."""

from typing import Any


def sort_feature_records(font) -> dict[str, int]:
    """Sort GSUB/GPOS feature tags without changing lookup or feature identity.

    Language systems and feature variations refer to numeric feature indexes.
    Validate every reference before mutation and move those references together
    with the records. Duplicate tags retain their original relative order.
    """
    plans = []
    for tag in ("GSUB", "GPOS"):
        if tag not in font:
            continue
        table = font[tag].table
        records = table.FeatureList.FeatureRecord
        order = sorted(range(len(records)), key=lambda index: records[index].FeatureTag)
        remap = {old: new for new, old in enumerate(order)}
        languages: list[Any] = []
        substitutions: list[Any] = []
        for script in table.ScriptList.ScriptRecord:
            languages.extend(row.LangSys for row in script.Script.LangSysRecord)
            if script.Script.DefaultLangSys is not None:
                languages.append(script.Script.DefaultLangSys)
        variations = getattr(table, "FeatureVariations", None)
        if variations:
            for variation in variations.FeatureVariationRecord:
                substitution = variation.FeatureTableSubstitution
                if substitution is not None:
                    substitutions.append(substitution)
        for language in languages:
            indexes = list(language.FeatureIndex)
            if language.ReqFeatureIndex != 0xFFFF:
                indexes.append(language.ReqFeatureIndex)
            if any(index not in remap for index in indexes):
                raise ValueError(f"{tag} language system references a missing feature")
        if any(
            record.FeatureIndex not in remap
            for substitution in substitutions
            for record in substitution.SubstitutionRecord
        ):
            raise ValueError(f"{tag} variation references a missing feature")
        plans.append((tag, table, records, order, remap, languages, substitutions))
    changed = {}
    for tag, table, records, order, remap, languages, substitutions in plans:
        if order == list(range(len(records))):
            continue
        table.FeatureList.FeatureRecord = [records[index] for index in order]
        for language in languages:
            language.FeatureIndex = sorted(remap[index] for index in language.FeatureIndex)
            if language.ReqFeatureIndex != 0xFFFF:
                language.ReqFeatureIndex = remap[language.ReqFeatureIndex]
        for substitution in substitutions:
            for record in substitution.SubstitutionRecord:
                record.FeatureIndex = remap[record.FeatureIndex]
            substitution.SubstitutionRecord.sort(key=lambda record: record.FeatureIndex)
        changed[tag] = len(records)
    return changed

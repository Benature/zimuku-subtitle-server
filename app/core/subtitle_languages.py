from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class SubtitleLanguage:
    code: str
    display_name: str
    filename_tag: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


SUBTITLE_LANGUAGES = (
    SubtitleLanguage(code="zh-CN", display_name="简体中文", filename_tag="zh-CN"),
    SubtitleLanguage(code="zh-TW", display_name="繁体中文", filename_tag="zh-TW"),
    SubtitleLanguage(code="en", display_name="英语", filename_tag="en"),
    SubtitleLanguage(code="zh-CN-en", display_name="简英双语", filename_tag="zh-CN-en"),
)

SUBTITLE_LANGUAGE_BY_CODE = {language.code: language for language in SUBTITLE_LANGUAGES}


def list_subtitle_languages() -> list[dict[str, str]]:
    return [language.to_dict() for language in SUBTITLE_LANGUAGES]

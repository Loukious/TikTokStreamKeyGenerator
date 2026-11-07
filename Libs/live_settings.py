"""Pre-LIVE settings shared by Studio and Android room creation.

Traced in Studio 1.37.4 and Android 47.1.4: AuthSwitch is 1=on, 2=off.
Disclosure booleans use lowercase strings; ecommerce state is a separate enum.
"""
from dataclasses import dataclass


CONTENT_DISCLOSURES = (
    ('Off', 'off'),
    ('Own brand', 'own_brand'),
    ('Third-party brand', 'third_party'),
    ('Own brand + third-party brand', 'both'),
)


@dataclass(frozen=True)
class LiveSettings:
    allow_gifts: bool = True
    allow_comments: bool = True
    content_disclosure: str = 'off'
    filter_comments: bool = True
    subscriber_only_chat: bool = False
    star_comments: bool | None = None
    filter_spam: bool = True
    filter_flagged: bool = False
    review_flagged: bool = False

    def __post_init__(self):
        if type(self.allow_gifts) is not bool or type(self.allow_comments) is not bool:
            raise ValueError('Allow gifts and allow comments must be true or false.')
        if not isinstance(self.content_disclosure, str) or self.content_disclosure not in {value for _, value in CONTENT_DISCLOSURES}:
            raise ValueError('Choose Off, Own brand, Third-party brand, or both for content disclosure.')
        for name in ('filter_comments', 'subscriber_only_chat', 'filter_spam', 'filter_flagged', 'review_flagged'):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f'{name.replace("_", " ")} must be true or false.')
        if self.star_comments is not None and type(self.star_comments) is not bool:
            raise ValueError('Star Comments must be true, false, or the account default.')
        if self.subscriber_only_chat and not self.allow_comments:
            raise ValueError('Allow comments before enabling subscriber-only chat.')

    def room_fields(self, implementation):
        if implementation not in ('pc', 'mobile'):
            raise ValueError('Unknown LIVE client implementation.')
        own_brand = self.content_disclosure in ('own_brand', 'both')
        third_party = self.content_disclosure in ('third_party', 'both')
        fields = {
            'gift_auth': '1' if self.allow_gifts else '2',
            'chat_auth': '1' if self.allow_comments else '2',
            'open_commercial_content_toggle': str(own_brand or third_party).lower(),
            'commercial_content_promote_myself': str(own_brand).lower(),
            'commercial_content_promote_third_party': str(third_party).lower(),
            'chat_l2' if implementation == 'pc' else 'chat_l_2': '1' if self.filter_comments else '2',
            'chat_sub_only_auth': '1' if self.subscriber_only_chat else '2',
        }
        if self.star_comments is not None:
            fields['star_comment_switch'] = str(self.star_comments).lower()
        if implementation == 'mobile':
            fields.update(spam_comments='1' if self.filter_spam else '2',
                          community_flagged_chat_auth='1' if self.filter_flagged else '2',
                          community_flagged_chat_review_auth='1' if self.review_flagged else '2')
        # These are explicit manual choices: third-party=5, off=0. Studio
        # omits the ecommerce field for off/own-brand; Android sends its state.
        if third_party:
            fields['ecom_bc_toggle'] = '5'
        elif implementation == 'mobile':
            fields['ecom_bc_toggle'] = '0'
        return fields

    def as_config(self):
        return {
            'allow_gifts': self.allow_gifts,
            'allow_comments': self.allow_comments,
            'content_disclosure': self.content_disclosure,
            'filter_comments': self.filter_comments,
            'subscriber_only_chat': self.subscriber_only_chat,
            'star_comments': self.star_comments,
            'filter_spam': self.filter_spam,
            'filter_flagged': self.filter_flagged,
            'review_flagged': self.review_flagged,
        }

    def room_conflicts(self, room):
        """Report explicit server contradictions; absent metadata is unverified."""
        auth = room.get('room_auth') or {}
        if not isinstance(auth, dict):
            return []
        return [label for key, allowed, label in (
            ('Gift', self.allow_gifts, 'gifts'), ('Chat', self.allow_comments, 'comments'),
        ) if not allowed and auth.get(key) in (True, 1, '1', 'true')]

    @classmethod
    def from_config(cls, config):
        # Accept JSON booleans; malformed values use the legacy defaults.
        def boolean(name, default=True):
            value = config.get(name, default)
            return value if type(value) is bool else default

        disclosure = config.get('content_disclosure', 'off')
        if not isinstance(disclosure, str) or disclosure not in {value for _, value in CONTENT_DISCLOSURES}:
            disclosure = 'off'
        star = config.get('star_comments')
        return cls(boolean('allow_gifts'), boolean('allow_comments'), disclosure,
                   filter_comments=boolean('filter_comments'),
                   subscriber_only_chat=boolean('subscriber_only_chat', False) and boolean('allow_comments'),
                   star_comments=star if type(star) is bool else None,
                   filter_spam=boolean('filter_spam'), filter_flagged=boolean('filter_flagged', False),
                   review_flagged=boolean('review_flagged', False))

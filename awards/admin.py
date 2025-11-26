from django.contrib import admin
from .models import AwardConfig, SuggestedCategory, Category, SuggestedNominee, Nominee, Vote

admin.site.register(AwardConfig)
admin.site.register(SuggestedCategory)
admin.site.register(Category)
admin.site.register(SuggestedNominee)
admin.site.register(Nominee)
admin.site.register(Vote)

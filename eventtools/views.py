from django.shortcuts import get_object_or_404, render_to_response
from django.template.context import RequestContext
from django.core.paginator import Paginator, EmptyPage, InvalidPage
from django.utils.safestring import mark_safe
from django.conf.urls.defaults import *
from django.http import HttpResponse
from eventtools.conf import settings
from eventtools.utils.pprint_timespan import humanized_date_range
from dateutil.relativedelta import relativedelta
from vobject import iCalendar


class EventViews(object):
    #define
    #event_qs
    #occurrence_qs
    
    def get_urls(self):
        return patterns('',
            url(r'^$', self.occurrence_list, name='occurrence_list'),
            url(r'^event/(?P<event_slug>[-\w]+)/$', self.event, name='event'),
            url(r'^(?P<occurrence_id>\d+)/?$', self.occurrence, name="occurrence"), #canonical URL for occurrence.
            url(r'^(?P<occurrence_id>\d+)(?P<ignored_part>\+.*)/?$', self.occurrence),
        
            # #ical
            url(r'^events\.ics$', self.occurrence_list_ical, name='occurrence_list_ical'),
            url(r'^event/(?P<event_slug>[-\w]+)/events\.ics$', self.event_ical, name='event_ical'),
            url(r'^(?P<occurrence_id>\d+)/events\.ics$', \
                self.occurrence_ical, name='occurrence_ical'),
        )
    
    def response_as_ical(self, request, occurrences):
        ical = iCalendar()
        ical.add('X-WR-CALNAME').value = settings.ICAL_CALNAME
        ical.add('X-WR-CALDESC').value = settings.ICAL_CALDESC
        ical.add('method').value = 'PUBLISH'  # IE/Outlook needs this
    
        if hasattr(occurrences, '__iter__'):
            for occ in occurrences:
                ical = occ.as_icalendar(ical, request)
        else:
            ical = occurrences.as_icalendar(ical, request)
        
        icalstream = ical.serialize()
        response = HttpResponse(icalstream, mimetype='text/calendar')
        response['Filename'] = 'events.ics'  # IE needs this
        response['Content-Disposition'] = 'attachment; filename=events.ics'

        return response
    


    #occurrence
    def _occurrence_context(self, request, occurrence_id):
        return {
            'occurrence': get_object_or_404(self.occurrence_qs, id=occurrence_id)
        }
    
    def occurrence(self, request, occurrence_id, ignored_part=None):
        context = self._occurrence_context(request, occurrence_id)
        return render_to_response('eventtools/occurrence.html', context, context_instance=RequestContext(request))

    def occurrence_ical(self, request, occurrence_id):
        context = self._occurrence_context(request, occurrence_id)
        return self.response_as_ical(request, [context['occurrence']])
        
    #event
    def _event_context(self, request, event_slug):
        event = get_object_or_404(self.event_qs, slug=event_slug)
        event_descendants = event.get_descendants(include_self=True)
        occurrence_pool = event_descendants.occurrences()

        return {
            'event': event,
            'event_children': event_descendants,
            'occurrence_pool': occurrence_pool,
        }

    def _paginate(self, request, pool):
        paginator = Paginator(pool, settings.OCCURRENCES_PER_PAGE)

        # Make sure page request is an int. If not, deliver first page.
        try:
            page = int(request.GET.get('page', '1'))
        except ValueError:
            page = 1

       # If page request (9999) is out of range, deliver last page of results.
        try:
            pageinfo = paginator.page(page)
        except (EmptyPage, InvalidPage):
            pageinfo = paginator.page(paginator.num_pages)

        return pageinfo
    
    def event(self, request, event_slug):
        event_context = self._event_context(request, event_slug)
        pageinfo = self._paginate(request, event_context['occurrence_pool'])
        
        event_context.update({
            'occurrence_page': pageinfo.object_list,
            'pageinfo': pageinfo,
        })

        return render_to_response('eventtools/occurrence_list.html', event_context, context_instance=RequestContext(request))
 
    def event_ical(self, request, event_slug):
        event_context = self._event_context(request, event_slug)
        return self.response_as_ical(request, event_context['occurrence_pool'])

    #occurrence_list
    def _occurrence_list_context(self, request, qs):
        occurrence_pool, date_bounds = qs.from_GET(request.GET)
        if date_bounds[0] is not None and date_bounds[1] is not None:
            # we're doing a date-bounded view. We can't keep the pool bound
            date_delta = relativedelta(date_bounds[1]+relativedelta(days=1), date_bounds[0])
    
            earlier = (date_bounds[0] - date_delta, date_bounds[1] - date_delta)
            later = (date_bounds[0] + date_delta, date_bounds[1] + date_delta) 
            
            pageinfo = {
                'date_span': mark_safe(humanized_date_range(*date_bounds, imply_year=False, space="&nbsp;", range_str="&ndash;")),
                'previous_date_span': {
                    'start': earlier[0].date().isoformat(),
                    'end': earlier[1].date().isoformat(),
                },
                'next_date_span': {
                    'start': later[0].date().isoformat(),
                    'end': later[1].date().isoformat(),
                },
                'date_delta': date_delta.days
            }
            
            return {
                'bounded': True,
                'pageinfo': pageinfo,
                'occurrence_pool': qs,
                'occurrence_page': occurrence_pool,            
            }
            
        else:         
            pageinfo = self._paginate(request, occurrence_pool)
            
            # we're paging through all events in the pool, OCCURRENCES_PER_PAGE at a time.
            paginator = Paginator(occurrence_pool, settings.OCCURRENCES_PER_PAGE)

            # Make sure page request is an int. If not, deliver first page.
            try:
                page = int(request.GET.get('page', '1'))
            except ValueError:
                page = 1

           # If page request (9999) is out of range, deliver last page of results.
            try:
                pageinfo = paginator.page(page)
            except (EmptyPage, InvalidPage):
                pageinfo = paginator.page(paginator.num_pages)

            return {
                'bounded': False,
                'pageinfo': pageinfo,
                'occurrence_pool': occurrence_pool,
                'occurrence_page': pageinfo.object_list,            
            }
    
    def occurrence_list(self, request): #probably want to override this for doing more filtering.
        occurrence_context = self._occurrence_list_context(request, self.occurrence_qs)

        if occurrence_context['bounded']: #2 dates given
            template = 'eventtools/occurrence_datespan.html'
        else:
            template = 'eventtools/occurrence_list.html'
            
        return render_to_response(template ,occurrence_context, context_instance=RequestContext(request))
        
    def occurrence_list_ical(self, request):
        occurrence_list_context = self._occurrence_list_context(request, self.occurrence_qs)
        pool = occurrence_list_context['occurrence_pool']
        return self.response_as_ical(request, pool)

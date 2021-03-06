from sleeps import *
from sleepergroups import *
from static import *

from django.template import RequestContext
from django.template.loader import render_to_string
from django.http import *
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, render_to_response
from django.core import serializers
from django.db.models import Q
from django.core.exceptions import *
from django.utils.timezone import now
from django.utils.decorators import method_decorator
from django.views.generic import CreateView
from django.core.cache import cache

from sleep.models import *
from sleep.forms import *

import datetime
import pytz
import csv

MAX_LEADERBOARD_SIZE = 10

@login_required
def graph(request):
    return render_to_response('graph.html', {"user": request.user, "sleeps": request.user.sleep_set.all().order_by('-end_time')}, context_instance=RequestContext(request))

class CreateGroup(CreateView):
    model = SleeperGroup
    template_name = 'create_group.html'
    fields = ['name', 'privacy', 'description']

    def form_valid(self, form):
        response = super(CreateGroup, self).form_valid(form)
        Membership(
            user=self.request.user,
            group=form.instance,
            privacy=self.request.user.sleeperprofile.privacyLoggedIn,
            role=Membership.ADMIN).save()
        return response

    @method_decorator(login_required)
    def dispatch(self, *args, **kwargs):
        return super(CreateView, self).dispatch(*args, **kwargs)

@login_required
def acceptInvite(request):
    if 'id' in request.POST and 'accepted' in request.POST:
        invites = GroupInvite.objects.filter(id=request.POST['id'],accepted=None)
        if len(invites)!=1:
            raise Http404
        invite = invites[0]
        if request.user.id is not invite.user_id:
            raise PermissionDenied
        if request.POST['accepted']=="True":
            invite.accept()
        else:
            invite.reject()
        return HttpResponse('')
    else:
        return HttpResponseBadRequest('')

@login_required
def inviteMember(request):
    if 'group' in request.POST and 'user' in request.POST:
        gid = request.POST['group']
        uid = request.POST['user']
        gs = SleeperGroup.objects.filter(id=gid)
        if len(gs)!=1 or request.user not in gs[0].members.all():
            raise Http404
        us = Sleeper.objects.filter(id=uid)
        if len(us)!=1:
            raise Http404
        g=gs[0]
        u=us[0]
        rs = GroupRequest.objects.filter(user = u, group = g, accepted=None)
        if rs.count() >= 1: #the user has made a request to join, accept them.
            rs[0].accept()
        else:
            g.invite(u,request.user)
        return HttpResponse('')
    else:
        return HttpResponseBadRequest('')

@login_required
def manageMember(request):
    if 'group' in request.POST and 'user' in request.POST:
        gid = request.POST['group']
        uid = request.POST['user']
        gs = SleeperGroup.objects.filter(id=gid)
        if len(gs)!=1 or request.user not in gs[0].members.all():
            raise Http404
        us = Sleeper.objects.filter(id=uid)
        if len(us)!=1:
            raise Http404
        g=gs[0]
        u=us[0]
        if not (request.user.pk == u.pk):
            ms = Membership.objects.filter(user=request.user, group=g)
            if ms.count() != 1: raise Http404
            m = ms[0]
            if m.role < m.ADMIN: raise PermissionDenied
        if 'action' in request.POST and request.POST["action"] == "remove":
            for m in Membership.objects.filter(user=u,group=g):
                r = m.removeMember()
                if r == "redirect": return HttpResponseRedirect("/groups")
            return HttpResponse('')
        if 'action' in request.POST and request.POST["action"] == "makeAdmin":
            for m in Membership.objects.filter(user=u,group=g):
                m.makeAdmin()
            return HttpResponse('')
        if 'action' in request.POST and request.POST["action"] == "removeAdmin":
            for m in Membership.objects.filter(user=u, group=g):
                try:
                    m.makeMember()
                except ValueError:
                    return HttpResponseBadRequest('')
            return HttpResponse('')
    else:
        return HttpResponseBadRequest('')

@login_required
def groupRequest(request):
    if 'group' in request.POST:
        gid = request.POST['group']
        gs = SleeperGroup.objects.filter(id=gid)
        if gs.count() != 1: raise Http404
        g = gs[0]
        if g.privacy < g.REQUEST: raise PermissionDenied
        if g.privacy >= g.PUBLIC: # it's a public group, allow user to join
            m = Membership(user=request.user, group=g, privacy = request.user.sleeperprofile.privacyLoggedIn)
            m.save()
        invites = GroupInvite.objects.filter(user=request.user, group=g, accepted = None)
        if invites.count() >= 1: # the user has already been invited, accept them.
            invites[0].accept()
        else:
            g.request(request.user)
        return HttpResponse('')
    else:
        return HttpResponseBadRequest('')

@login_required
def groupJoin(request):
    if 'group' in request.POST:
        gid = request.POST['group']
        gs = SleeperGroup.objects.filter(id=gid)
        if gs.count() != 1: raise Http404
        g = gs[0]
        if g.privacy < SleeperGroup.PUBLIC: raise PermissionDenied
        m = Membership(user = request.user, group = g, privacy = request.user.sleeperprofile.privacyLoggedIn)
        m.save()
        return HttpResponse('')
    else:
        return HttpResponseBadRequest('')

@login_required
def processRequest(request):
    if 'id' in request.POST:
        rs = GroupRequest.objects.filter(id=request.POST["id"])
        if rs.count() != 1: raise Http404
        r = rs[0]
        m = Membership.objects.get(group=r.group, user=request.user)
        if m.role < m.ADMIN: raise PermissionDenied
        if "accepted" in request.POST:
            if request.POST["accepted"] == "True":
                r.accept()
            elif request.POST["accepted"] == "False":
                r.reject()
            return HttpResponse('')
        return HttpResponseBadRequest('')
    else:
        return HttpResponseBadRequest('')

@login_required
def manageGroup(request,gid):
    gs=SleeperGroup.objects.filter(id=gid)
    if len(gs)!=1:
        raise Http404
    g=gs[0]
    if request.user not in g.members.all():
        raise PermissionDenied
    context={
            'group':g,
            'isAdmin': (request.user.membership_set.get(group = g).role >= 50),
            }
    m = request.user.membership_set.get(group = g)
    if request.method == 'POST' and "SleeperSearchForm" in request.POST:
        searchForm=SleeperSearchForm(request.POST)
        if searchForm.is_valid():
            us=User.objects.filter(username__icontains=searchForm.cleaned_data['username']).exclude(sleepergroups__id=g.id)
            context['results']=us
            context['showResults'] = True
            context['count']=us.count()
    else:
        searchForm = SleeperSearchForm()
    if request.method == 'POST' and "GroupForm" in request.POST:
        if context['isAdmin'] == False:
            raise PermissionDenied
        groupForm = GroupForm(request.POST, instance=g)
        if groupForm.is_valid():
            if 'delete' in groupForm.data and groupForm.data['delete'] == 'on':
                g.delete()
                return HttpResponseRedirect('/groups/')
            groupForm.save()
        else:
            context['page'] = 2
    else:
        groupForm = GroupForm(instance=g)
    if request.method == 'POST' and "MembershipForm" in request.POST:
        membershipForm = MembershipForm(request.POST, instance=m)
        if membershipForm.is_valid():
            membershipForm.save()
    else:
        membershipForm = MembershipForm(instance=m)
    context['searchForm']=searchForm
    context['groupForm']=groupForm
    context['membershipForm'] = membershipForm
    context['members']=g.members.all()
    if context['isAdmin']:
        context['requests'] = g.grouprequest_set.filter(accepted=None)
        if 'page' not in context and context['requests'].count() > 0: context['page'] = 3
    return render_to_response('manage_group.html',context,context_instance=RequestContext(request))

def leaderboard(request,group_id=None):
    if request.user.is_authenticated():
        user_metrics = request.user.sleeperprofile.metrics.all()
    else:
        user_metrics = Metric.objects.filter(show_by_default=True)

    if 'sort' not in request.GET or request.GET['sort'] not in [m.name for m in user_metrics]:
        sort_by = 'zScore'
    else:
        sort_by = request.GET['sort']
    
    if group_id is None:
        board_size = MAX_LEADERBOARD_SIZE
        group = None
    else:
        try:
            group = SleeperGroup.objects.get(id=group_id)
        except SleeperGroup.DoesNotExist:
            raise Http404
        if request.user not in group.members.all():
            raise PermissionDenied
        num_members = group.members.count()
        # don't show bottom half of leaderboard for sufficiently large groups:
        # we don't want to encourage bad sleep behavior
        board_size = num_members if num_members < 4 else min(MAX_LEADERBOARD_SIZE, num_members//2)

    ss = Sleeper.objects.sorted_sleepers(sortBy=sort_by,user=request.user,group=group)
    top = [ s for s in ss if s['rank'] <= board_size or request.user.is_authenticated() and s['user'].pk==request.user.pk ]

    numLeaderboard = len([s for s in ss if s['rank']!='n/a'])
    n = now()
    
    try:
        recent_winner = Sleeper.objects.bestByTime(start=n-datetime.timedelta(3),end=n,user=request.user,group=group)[0]
    except IndexError:
        return HttpResponseBadRequest("Can't load leaderboard if there are no users")
        
    if group:
        allUsers = group.members.all()
    else:
        allUsers = Sleeper.objects.all()
    number = allUsers.filter(sleep__isnull=False).distinct().count()
    context = {
            'group' : group,
            'top' : top,
            'recentWinner' : recent_winner,
            'total' : Sleep.objects.totalSleep(group=group),
            'number' : number,
            'numLeaderboard' : numLeaderboard,
            'leaderboard_valid' : len(ss),
            'userMetrics' : user_metrics
            }
    return render_to_response('leaderboard.html',context,context_instance=RequestContext(request))

def graphs(request,group=None):
    if group is not None:
        gs = SleeperGroup.objects.filter(id=group)
        if gs.count()!=1:
            raise Http404
        group = gs[0]
        if request.user not in group.members.all():
            raise PermissionDenied
    return render_to_response('graphs.html',{'group': group},context_instance=RequestContext(request))

def creep(request,username=None):
    if not username:
        if request.user.is_anonymous():
            creepable=Sleeper.objects.filter(sleeperprofile__privacy__gte=SleeperProfile.PRIVACY_STATS)
            followed = []
        else:
            creepable=Sleeper.objects.filter(
                    Q(sleeperprofile__privacyLoggedIn__gte=SleeperProfile.PRIVACY_STATS) | 
                    (
                        Q(sleeperprofile__privacyFriends__gte=SleeperProfile.PRIVACY_STATS) &
                        Q(sleeperprofile__friends=request.user)
                    )
                )
            followed = request.user.sleeperprofile.follows.order_by('username')
        total=creepable.distinct().count()
        if request.method == 'POST':
            form=SleeperSearchForm(request.POST)
            if form.is_valid():
                users = creepable.filter(username__icontains=form.cleaned_data['username']).distinct()
                count = users.count()
                if count==1: return HttpResponseRedirect('/creep/%s/' % users[0].username)
                else:
                    context = {
                            'results' : users,
                            'count' : count,
                            'form' : form,
                            'new' : False,
                            'total' : total,
                            'followed' : followed,
                            }
                    return render_to_response('creepsearch.html',context,context_instance=RequestContext(request))
        else:
            form = SleeperSearchForm()
        context = {
                'form' : form,
                'new' : True,
                'total' : total,
                'followed' : followed,
                }
        return render_to_response('creepsearch.html',context,context_instance=RequestContext(request))
    else:
        context = {}
        try:
            user=Sleeper.objects.get(username=username)
            p = user.sleeperprofile
            if p.user_id == request.user.id and "as" in request.GET:
                priv = p.checkPermissions(request.GET['as'])
            else:
                priv = p.getPermissions(request.user)
            if not(request.user.is_anonymous()) and request.user.pk == user.pk: context["isself"] =True
            if priv<=p.PRIVACY_NORMAL: return render_to_response('creepfailed.html',{},context_instance=RequestContext(request))
        except:
            return render_to_response('creepfailed.html',{},context_instance=RequestContext(request))
        context.update({'user' : user,'global' : user.decayStats()})
        if priv>=p.PRIVACY_PUBLIC: context['sleeps']=user.sleep_set.all().order_by('-end_time')
        if priv>=p.PRIVACY_GRAPHS:
            if "type" in request.GET and request.GET["type"] == "graph": return render_to_response('graph.html',context,context_instance=RequestContext(request))
            context["graphs"] = True
        return render_to_response('creep.html',context,context_instance=RequestContext(request))

@login_required
def editProfile(request):
    p = request.user.sleeperprofile
    if p.use12HourTime: fmt = "%I:%M %p"
    else: fmt = "%H:%M"
    if request.method == 'POST':
        form = SleeperProfileForm(fmt, request.POST, instance=p)
        context = {"form":form}
        if form.is_valid():
            form.save()
            return HttpResponseRedirect('/editprofile/?success=True')
        else:
            for k in form.errors.viewkeys():
                if "ideal" in k:
                    context["page"] = 2
                    break
    else:
        initial = {"idealWakeupWeekend": p.idealWakeupWeekend.strftime(fmt),
                "idealWakeupWeekday": p.idealWakeupWeekday.strftime(fmt),
                "idealSleepTimeWeekend": p.idealSleepTimeWeekend.strftime(fmt),
                "idealSleepTimeWeekday": p.idealSleepTimeWeekday.strftime(fmt),}
        form = SleeperProfileForm(fmt, instance=p, initial = initial)
        context = {"form":form}
        if "success" in request.GET and request.GET["success"] == "True": context["success"] = True
    return render_to_response('editprofile.html', context ,context_instance=RequestContext(request))

@login_required
def exportSleeps(request):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="zscore_sleeps_' + request.user.username + '.csv"'
    
    writer = csv.writer(response)
    writer.writerow(["Start Time", "End Time", "Date", "Comments", "Timezone", "Quality"])

    for s in request.user.sleep_set.all():
        writer.writerow([s.start_local_time(), s.end_local_time(), s.date, s.comments, s.timezone, s.quality])

    return response

@login_required
def friends(request):
    prof = request.user.sleeperprofile
    friendfollow = (prof.friends.all() | prof.follows.all()).distinct().order_by('username').select_related('sleeperprofile').prefetch_related('sleeperprofile__friends','sleeperprofile__follows')
    requests = request.user.requests.filter(friendrequest__accepted=None).order_by('user__username')
    if request.method == 'POST':
        form=SleeperSearchForm(request.POST)
        if form.is_valid():
            users = User.objects.filter(username__icontains=form.cleaned_data['username']).exclude(pk=request.user.pk).distinct()
            count = users.count()
            context = {
                    'results' : users,
                    'count' : count,
                    'form' : form,
                    'new' : False,
                    'friendfollow' : friendfollow,
                    'requests' : requests,
                    }
            return render_to_response('friends.html',context,context_instance=RequestContext(request))
    else:
        form = SleeperSearchForm()
    context = {
            'form' : form,
            'new' : True,
            'friendfollow' : friendfollow,
            'requests' : requests,
            }
    return render_to_response('friends.html',context,context_instance=RequestContext(request))
          
@login_required
def requestFriend(request):
    if 'id' in request.POST:
        i = request.POST['id']
        if i==request.user.pk or len(User.objects.filter(pk=i))!=1:
            raise Http404
        them = Sleeper.objects.get(pk=i)
        if not FriendRequest.objects.filter(requestor=request.user.sleeperprofile,requestee=them):
            if request.user in them.sleeperprofile.friends.all():
                accept = True
            else:
                accept = None
            FriendRequest.objects.create(requestor=request.user.sleeperprofile,requestee=them,accepted=accept)
        return HttpResponse('')
    else:
        return HttpResponseBadRequest('')

@login_required
def hideRequest(request):
    if 'id' in request.POST:
        i = request.POST['id']
        if i==request.user.pk or len(User.objects.filter(pk=i))!=1:
            raise Http404
        frs = FriendRequest.objects.filter(requestor__user__pk=i,requestee=request.user)
        for fr in frs:
            fr.accepted=False
            fr.save()
        return HttpResponse('')
    else:
        return HttpResponseBadRequest('')

@login_required
def addFriend(request):
    if 'id' in request.POST:
        i = request.POST['id']
        if i==request.user.pk or len(User.objects.filter(pk=i))!=1:
            raise Http404
        prof = request.user.sleeperprofile
        prof.friends.add(i)
        prof.save()
        frs = FriendRequest.objects.filter(requestor__user__pk=i,requestee=request.user)
        for fr in frs:
            fr.accepted=True
            fr.save()
        return HttpResponse('')
    else:
        return HttpResponseBadRequest('')

@login_required
def removeFriend(request):
    if 'id' in request.POST:
        i = request.POST['id']
        if i==request.user.pk or len(User.objects.filter(pk=i))!=1:
            raise Http404
        prof = request.user.sleeperprofile
        prof.friends.remove(i)
        return HttpResponse('')
    else:
        return HttpResponseBadRequest('')

@login_required
def follow(request):
    if 'id' in request.POST:
        i = request.POST['id']
        if i==request.user.pk or len(User.objects.filter(pk=i))!=1:
            raise Http404
        prof = request.user.sleeperprofile
        prof.follows.add(i)
        prof.save()
        return HttpResponse('')
    else:
        return HttpResponseBadRequest('')

@login_required
def unfollow(request):
    if 'id' in request.POST:
        i = request.POST['id']
        if i==request.user.pk or len(User.objects.filter(pk=i))!=1:
            raise Http404
        prof = request.user.sleeperprofile
        prof.follows.remove(i)
        return HttpResponse('')
    else:
        return HttpResponseBadRequest('')

@login_required
def createSleep(request):
    # Date-ify start, end, and center
    timezone = pytz.timezone(request.POST['timezone'])
    start = datetime.datetime(*(map(int, request.POST.getlist("start[]"))))
    start=timezone.localize(start)
    end = datetime.datetime(*(map(int, request.POST.getlist("end[]"))))
    end=timezone.localize(end)
    date = datetime.date(*(map(int, request.POST.getlist("date[]"))[:3]))
    # Pull out comments
    if "comments" in request.POST:
        comments = request.POST["comments"]
    else:
        comments = ""
    # Create the Sleep instance
    if start > end: start,end = end, start #if end is after start, flip them
    s = Sleep(user=request.user, start_time=start, end_time=end, comments=comments, date=date,timezone=timezone)
    try:
        s.validate_unique()
        s.save()
    except ValidationError:
        return HttpResponseBadRequest('')
    return HttpResponse('')

@login_required
def createPartialSleep(request):
    created = PartialSleep.create_new_for_user(request.user)
    if created:
        return HttpResponseRedirect("/mysleep/")
    else:
        return HttpResponseBadRequest("")

@login_required
def finishPartialSleep(request):
    try:
        s = PartialSleep.finish_for_user(request.user)
        return HttpResponseRedirect("/sleep/edit/" + str(s.pk) + "/?from=partial")
    except ValidationError:
        return HttpResponseRedirect("/sleep/simple/?error=partial")
    except PartialSleep.DoesNotExist:
        return HttpResponseBadRequest("")

@login_required
def deletePartialSleep(request):
    p = request.user.partialsleep_set.first()
    if p is not None:
        p.delete()
        if "next" in request.GET: return HttpResponseRedirect(request.GET["next"])
        return HttpResponseRedirect("/")
    else:
        return HttpResponseBadRequest('')

@login_required
def deleteSleep(request):
    if 'id' in request.POST:
        i = request.POST['id']
        s = Sleep.objects.filter(pk=i)
        if len(s) == 0:
            raise Http404
        s = s[0]
        if s.user != request.user:
            raise PermissionDenied
        s.delete()
        return HttpResponse('')
    return HttpResponseBadRequest('')

@login_required
def deleteAllnighter(request):
    if 'id' in request.POST:
        i = request.POST['id']
        a = Allnighter.objects.filter(pk=i)
        if len(a) == 0: raise Http404
        a = a[0]
        if a.user != request.user: raise PermissionDenied
        a.delete()
        return HttpResponse('')
    return HttpResponseBadRequest('')

@login_required
def getSleepsJSON(request):
    u = request.user
    sleeps = list(Sleep.objects.filter(user=u))
    for sleep in sleeps:
        tz = pytz.timezone(sleep.timezone)
        #warning: the following is kind of hacky but it's better than dealing with the timezones in JS.  JS doesn't understand timezones, so we convert the timezone server-side, then pass it through to JS without telling the JS what timezone it's in.  JS interprets it as local time, which is slightly incorrect but works since all we want to do is get the hours/minutes/seconds back out as local time.
        sleep.start_time=sleep.start_time.astimezone(tz).replace(tzinfo=None)
        sleep.end_time=sleep.end_time.astimezone(tz).replace(tzinfo=None)
    data = serializers.serialize('json', sleeps)
    return HttpResponse(data, content_type='application/json')

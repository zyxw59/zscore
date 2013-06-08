from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import *

import pytz
import datetime
import math
import itertools

from zscore import settings

TIMEZONES = [ (i,i) for i in pytz.common_timezones]

class SleeperManager(models.Manager):
    def sorted_sleepers(self,sortBy='zScore',user=None):
        sleepers = Sleeper.objects.all().prefetch_related('sleep_set','sleeperprofile')
        scored=[]
        extra=[]
        for sleeper in sleepers:
            if len(sleeper.sleepPerDay())>2 and sleeper.sleepPerDay(packDates=True)[-1]['date'] >= datetime.date.today()-datetime.timedelta(5):
                p = sleeper.sleeperprofile
                if user is None:
                    priv = p.PRIVACY_HIDDEN
                elif user is 'all':
                    priv = p.PRIVACY_PUBLIC
                elif user.is_anonymous():
                    priv = p.privacy
                elif user.pk==sleeper.pk:
                    priv = p.PRIVACY_PUBLIC
                else:
                    priv = p.privacyLoggedIn

                if priv<=p.PRIVACY_REDACTED:
                    sleeper.displayName="[redacted]"
                else:
                    sleeper.displayName=sleeper.username
                if priv>p.PRIVACY_HIDDEN:
                    d=sleeper.decayStats()
                    d['user']=sleeper
                    if 'is_authenticated' in dir(user) and user.is_authenticated():
                        if user.pk==sleeper.pk:
                            d['opcode']='me' #I'm using opcodes to mark specific users as self or friend.
                    else:
                        d['opcode'] = None
                    scored.append(d)
            else:
                if 'is_authenticated' in dir(user) and user.is_authenticated() and user.pk == sleeper.pk:
                    d = sleeper.decayStats()
                    d['rank']='n/a'
                    sleeper.displayName=sleeper.username
                    d['user']=sleeper
                    d['opcode']='me'
                    extra.append(d)
        if sortBy in ['stDev']:
            scored.sort(key=lambda x: x[sortBy])
        else:
            scored.sort(key=lambda x: -x[sortBy])
        for i in xrange(len(scored)):
            scored[i]['rank']=i+1
        return scored+extra

    def bestByTime(self,start=datetime.datetime.min,end=datetime.datetime.max,user=None):
        sleepers = Sleeper.objects.all().prefetch_related('sleep_set','sleeperprofile')
        scored=[]
        for sleeper in sleepers:
            p = sleeper.sleeperprofile
            if user is None:
                priv = p.PRIVACY_HIDDEN
            elif user is 'all':
                priv = p.PRIVACY_PUBLIC
            elif user.is_anonymous():
                priv = p.privacy
            elif user.pk==sleeper.pk:
                priv = p.PRIVACY_PUBLIC
            else:
                priv = p.privacyLoggedIn

            if priv<=p.PRIVACY_REDACTED:
                sleeper.displayName="[redacted]"
            else:
                sleeper.displayName=sleeper.username
            if priv>p.PRIVACY_HIDDEN:
                d={'time':sleeper.timeSleptByTime(start,end)}
                d['user']=sleeper
                if 'is_authenticated' in dir(user) and user.is_authenticated():
                    if user.pk==sleeper.pk:
                        d['opcode']='me' #I'm using opcodes to mark specific users as self or friend.
                else:
                    d['opcode'] = None
                scored.append(d)
        scored.sort(key=lambda x: -x['time'])
        for i in xrange(len(scored)):
            scored[i]['rank']=i+1
        return scored

class Sleeper(User):
    class Meta:
        proxy = True

    objects = SleeperManager()

    def getOrCreateProfile(self):
        print "You probably don't actually want this method, User.sleeperprofile should work just fine."
        return SleeperProfile.objects.get_or_create(user=self)[0]

    def timeSleptByDate(self,start=datetime.date.min,end=datetime.date.max):
        sleeps = self.sleep_set.filter(date__gte=start,date__lte=end)
        return sum([s.end_time-s.start_time for s in sleeps],datetime.timedelta(0))

    def timeSleptByTime(self,start=datetime.datetime.min,end=datetime.datetime.max):
        sleeps = self.sleep_set.filter(end_time__gt=start,start_time__lt=end)
        return sum([min(s.end_time,end)-max(s.start_time,start) for s in sleeps],datetime.timedelta(0))

    def sleepPerDay(self,start=datetime.date.min,end=datetime.date.max,packDates=False,hours=False):
        if start==datetime.date.min and end==datetime.date.max:
            sleeps = self.sleep_set.values('date','start_time','end_time')
        else:
            sleeps = self.sleep_set.filter(date__gte=start,date__lte=end).values('date','start_time','end_time')
        if sleeps:
            dates=map(lambda x: x['date'], sleeps)
            first = min(dates)
            last = max(dates)
            n = (last-first).days + 1
            dateRange = [first + datetime.timedelta(i) for i in range(0,n)]
            byDays = [sum([(s['end_time']-s['start_time']).total_seconds() for s in filter(lambda x: x['date']==d,sleeps)]) for d in dateRange]
            if hours:
                byDays = map(lambda x: x/3600,byDays)
            if packDates:
                return [{'date' : first + datetime.timedelta(i), 'slept' : byDays[i]} for i in range(0,n)]
            else:
                return byDays
        else:
            return []

    def genDays(start,end):
        d=start
        while d <= end:
            yield d
            d += datetime.timedelta(1)

    def sleepWakeTime(self,t='end',start=datetime.date.today(),end=datetime.date.today()):
        sleeps = self.sleep_set.filter(date__gte=start,date__lte=end)
        if t=='end':
            f=Sleep.end_local_time
        elif t=='start':
            f=Sleep.start_local_time
        else:
            return None
        datestimes = [(s.date, f(s)) for s in sleeps if s.length() >= datetime.timedelta(hours=3)]
        daily={}
        for i in datestimes:
            if i[0] in daily:
                daily[i[0]]=max(daily[i[0]],i[1])
            else:
                daily[i[0]]=i[1]
        seconds = [t.time().hour*3600 + t.time().minute*60 + t.time().second for t in daily.itervalues()]
        if daily:
            av = sum(seconds)/len(seconds)
            return datetime.time(int(math.floor(av/3600)), int(math.floor((av%3600)/60)), int(math.floor((av%60))))
        else:
            return None

    def goToSleepTime(self, date=datetime.date.today()):
        return self.sleepWakeTime('start',date,date)

    def avgGoToSleepTime(self, start = datetime.date.min, end=datetime.date.max):
        return self.sleepWakeTime('start',start,end)

    def wakeUpTime(self, date=datetime.date.today()):
        return self.sleepWakeTime('end',date,date)

    def avgWakeUpTime(self, start = datetime.date.min, end=datetime.date.max):
        return self.sleepWakeTime('end',start,end)

    def movingStats(self,start=datetime.date.min,end=datetime.date.max):
        sleep = self.sleepPerDay(start,end)
        d = {}
        try:
            avg = sum(sleep)/len(sleep)
            d['avg']=avg
            if len(sleep)>2:
                stDev = math.sqrt(sum(map(lambda x: (x-avg)**2, sleep))/(len(sleep)-1.5)) #subtracting 1.5 is correct according to wikipedia
                d['stDev']=stDev
                d['zScore']=avg-stDev
        except:
            pass
        try:
            offset = 60*60.
            avgRecip = 1/(sum(map(lambda x: 1/(offset+x),sleep))/len(sleep))-offset
            d['avgRecip']=avgRecip
            avgSqrt = (sum(map(lambda x: math.sqrt(x),sleep))/len(sleep))**2
            d['avgSqrt']=avgSqrt
            avgLog = math.exp(sum(map(lambda x: math.log(x+offset),sleep))/len(sleep))-offset
            d['avgLog']=avgLog
        except:
            pass
        for k in ['avg','stDev','zScore','avgSqrt','avgLog','avgRecip']:
            if k not in d:
                d[k]=datetime.timedelta(0)
            else:
                d[k]=datetime.timedelta(0,d[k])
        return d

    def decaying(self,data,hl,stDev=False):
        s = 0
        w = 0
        for i in range(len(data)):
            s+=2**(-i/float(hl))*data[-i-1]
            w+=2**(-i/float(hl))
        if stDev:
            w = w*(len(data)-1.5)/len(data)
        return s/w

    def decayStats(self,end=datetime.date.max,hl=4):
        sleep = self.sleepPerDay(datetime.date.min,end)
        d = {}
        try:
            avg = self.decaying(sleep,hl)
            d['avg']=avg
            stDev = math.sqrt(self.decaying(map(lambda x: (x-avg)**2,sleep),hl,True))
            d['stDev']=stDev
            d['zScore']=avg-stDev
        except:
            pass
        try:
            offset = 60*60.
            avgRecip = 1/(self.decaying(map(lambda x: 1/(offset+x),sleep),hl))-offset
            d['avgRecip']=avgRecip
            avgSqrt = self.decaying(map(lambda x: math.sqrt(x),sleep),hl)**2
            d['avgSqrt']=avgSqrt
            avgLog = math.exp(self.decaying(map(lambda x: math.log(x+offset),sleep),hl))-offset
            d['avgLog']=avgLog
        except:
            pass
        for k in ['avg','stDev','zScore','avgSqrt','avgLog','avgRecip']:
            if k not in d:
                d[k]=datetime.timedelta(0)
            else:
                d[k]=datetime.timedelta(0,d[k])
        return d

class SleepManager(models.Manager):
    def totalSleep(self):
        sleeps =  Sleep.objects.all()
        return sum((sleep.end_time - sleep.start_time for sleep in sleeps),datetime.timedelta(0))

    def sleepTimes(self,res=1):
        sleeps = Sleep.objects.all()
        atTime = [0] * (24 * 60 / res) 
        for sleep in sleeps:
            tz = pytz.timezone(sleep.timezone)
            startDate = sleep.start_time.astimezone(tz).date()
            endDate = sleep.end_time.astimezone(tz).date()
            dr = [startDate + datetime.timedelta(i) for i in range((endDate-startDate).days + 1)]
            for d in dr:
                if d == startDate:
                    startTime = sleep.start_time.astimezone(tz).time()
                else:
                    startTime = datetime.time(0)
                if d == endDate:
                    endTime = sleep.end_time.astimezone(tz).time()
                else:
                    endTime = datetime.time(23,59)
                for i in range((startTime.hour * 60 + startTime.minute) / res, (endTime.hour * 60 + endTime.minute + 1) / res):
                    atTime[i]+=1
        return atTime

    def sleepStartEndTimes(self,res=10):
        sleeps = Sleep.objects.all()
        startAtTime = [0] * (24 * 60 / res)
        endAtTime = [0] * (24 * 60 / res)
        for sleep in sleeps:
            tz = pytz.timezone(sleep.timezone)
            startTime = sleep.start_time.astimezone(tz).time()
            endTime = sleep.end_time.astimezone(tz).time()
            startAtTime[(startTime.hour * 60 + startTime.minute) / res]+=1
            endAtTime[(endTime.hour * 60 + endTime.minute) / res]+=1
        return (startAtTime,endAtTime)

    def sleepLengths(self,res=10):
        sleeps = Sleep.objects.all()
        lengths = map(lambda x: x.length().total_seconds() / (60*res),sleeps)
        packed = [0] * int(max(lengths)+1)
        for length in lengths:
            if length>0:
                packed[int(length)]+=1
        return packed

class Sleep(models.Model):
    objects = SleepManager()

    user = models.ForeignKey(Sleeper)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    comments = models.TextField(blank=True)
    date = models.DateField()
    timezone = models.CharField(max_length=255, choices = TIMEZONES, default=settings.TIME_ZONE)

    def __unicode__(self):
        tformat = "%I:%M %p %x" if self.user.sleeperprofile.use12HourTime else "%H:%M %x" 
        return "Sleep from %s to %s (%s)" % (self.start_local_time().strftime(tformat),self.end_local_time().strftime(tformat), self.getTZShortName())

    def length(self):
        return self.end_time - self.start_time

    def validate_unique(self, exclude=None):
        overlaps = Sleep.objects.filter(start_time__lt=self.end_time,end_time__gt=self.start_time,user=self.user).exclude(pk = self.pk)
        if overlaps:
            raise ValidationError({NON_FIELD_ERRORS: ["This sleep overlaps with %s!" % overlaps[0]]})

    def start_local_time(self):
        tz = pytz.timezone(self.timezone)
        return self.start_time.astimezone(tz)

    def end_local_time(self):
        tz = pytz.timezone(self.timezone)
        return self.end_time.astimezone(tz)
    
    def getSleepTZ(self):
        """Returns the timezone as a timezone object"""
        return pytz.timezone(self.timezone)

    def updateTZ(self,tzname):
        """Updates the timezone while keeping the local time the same.  Intended for use from the shell; use at your own risk."""
        newtz = pytz.timezone(tzname)
        self.start_time = newtz.localize(self.start_local_time().replace(tzinfo=None))
        self.end_time = newtz.localize(self.end_local_time().replace(tzinfo=None))
        self.timezone = tzname #we have to make sure to do this last!
        self.save()

    def getTZShortName(self):
        """Gets the short of a time zone"""
        return self.getSleepTZ().tzname(datetime.datetime(self.date.year, self.date.month, self.date.day))

class Allnighter(models.Model):
    user = models.ForeignKey(Sleeper)
    date = models.DateField()
    comments = models.TextField(blank=True)

    def validate_unique(self, exclude=None):
        #Should edit to include the exclude field)
        try: user= self.user
        except:return None
        allnighterq = self.user.allnighter_set.all()


class SleeperProfile(models.Model):
    user = models.OneToOneField(Sleeper)
    # all other fields should have a default
    PRIVACY_HIDDEN = -100
    PRIVACY_REDACTED = -50
    PRIVACY_NORMAL = 0
    PRIVACY_STATS = 50
    PRIVACY_PUBLIC = 100
    PRIVACY_CHOICES = (
            (PRIVACY_HIDDEN, 'Hidden'),
            (PRIVACY_REDACTED, 'Redacted'),
            (PRIVACY_NORMAL, 'Normal'),
            (PRIVACY_STATS, 'Stats Public'),
            (PRIVACY_PUBLIC, 'Sleep Public'),
            )
    privacy = models.SmallIntegerField(choices=PRIVACY_CHOICES,default=PRIVACY_NORMAL,verbose_name='Privacy to anonymous users')
    privacyLoggedIn = models.SmallIntegerField(choices=PRIVACY_CHOICES,default=PRIVACY_NORMAL,verbose_name='Privacy to logged-in users')
    privacyFriends = models.SmallIntegerField(choices=PRIVACY_CHOICES,default=PRIVACY_NORMAL,verbose_name='Privacy to friends')
    friends = models.ManyToManyField(Sleeper,related_name='friends+',blank=True)
    follows = models.ManyToManyField(Sleeper,related_name='follows+',blank=True)
    requested = models.ManyToManyField(Sleeper,related_name='requests',blank=True,through='FriendRequest')
    use12HourTime = models.BooleanField(default=False)

    emailreminders = models.BooleanField(default=False)

    timezone = models.CharField(max_length=255, choices = TIMEZONES, default=settings.TIME_ZONE)

    idealSleep = models.DecimalField(max_digits=4, decimal_places=2, default = 7.5)
    #Decimalfield restricts to two decimal places, float would not.

    def getIdealSleep(self):
        """Returns idealSleep as a timedelta"""
        return datetime.timedelta(hours=float(self.idealSleep))

    def getUserTZ(self):
        """Returns user timezone as a timezone object"""
        return pytz.timezone(self.timezone)

    def __unicode__(self):
        return "SleeperProfile for user %s" % self.user



class FriendRequest(models.Model):
    requestor = models.ForeignKey(SleeperProfile)
    requestee = models.ForeignKey(Sleeper)
    accepted = models.NullBooleanField()
        


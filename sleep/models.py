from django.db import models
from django.contrib.auth.models import User

import datetime
import math

class SleepManager(models.Manager):
    def totalSleep(self):
        sleeps =  Sleep.objects.all()
        return sum((sleep.end_time - sleep.start_time for sleep in sleeps),datetime.timedelta(0))

class Sleep(models.Model):
    objects = SleepManager()

    user = models.ForeignKey(User)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    comments = models.TextField(blank=True)
    date = models.DateField()

    def __unicode__(self):
        return "Sleep from %s to %s" % (self.start_time,self.end_time)

    def length(self):
        return self.end_time - self.start_time

class SleeperProfile(models.Model):
    user = models.OneToOneField(User)
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
    privacy = models.SmallIntegerField(choices=PRIVACY_CHOICES,default=PRIVACY_NORMAL)
    use12HourTime = models.BooleanField(default=False)

    def __unicode__(self):
        return "SleeperProfile for user %s" % self.user

class SleeperManager(models.Manager):
    def sorted_sleepers(self,sortBy='zScore'):
        sleepers = Sleeper.objects.all().prefetch_related('sleep_set')
        scored=[]
        for sleeper in sleepers:
            if sleeper.sleep_set.count()>2:
                p = sleeper.getOrCreateProfile()
                if p.privacy<=p.PRIVACY_REDACTED:
                    sleeper.displayName="[redacted]"
                else:
                    sleeper.displayName=sleeper.username
                if p.privacy>p.PRIVACY_HIDDEN:
                    d=sleeper.movingStats()
                    d['user']=sleeper
                    scored.append(d)
        scored.sort(key=lambda x: -x[sortBy])
        for i in xrange(len(scored)):
            scored[i]['rank']=i+1
        return scored
        




class Sleeper(User):
    class Meta:
        proxy = True

    objects = SleeperManager()

    def getOrCreateProfile(self):
        return SleeperProfile.objects.get_or_create(user=self)[0]

    def timeSlept(self,start=datetime.date.min,end=datetime.datetime.max):
        sleeps = self.sleep_set.filter(date__gte=start,date__lte=end)
        return sum([s.end_time-s.start_time for s in sleeps],datetime.timedelta(0))

    def sleepPerDay(self,start=datetime.date.min,end=datetime.date.max,packDates=False,hours=False):
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
            avgSqrt = (sum(map(lambda x: math.sqrt(x),sleep))/len(sleep))**2
            d['avgSqrt']=avgSqrt
        except:
            pass
        for k in ['avg','stDev','zScore','avgSqrt']:
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

    def decayStats(self,end=datetime.date.max,hl=3):
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
            avgSqrt = self.decaying(map(lambda x: math.sqrt(x),sleep),hl)**2
            d['avgSqrt']=avgSqrt
        except:
            pass
        for k in ['avg','stDev','zScore','avgSqrt']:
            if k not in d:
                d[k]=datetime.timedelta(0)
            else:
                d[k]=datetime.timedelta(0,d[k])
        return d


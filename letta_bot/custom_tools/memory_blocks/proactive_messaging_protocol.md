# Proactive messaging protocol: Technical Memo

## Two Tools for Proactive Behavior

1. **schedule_message** - Schedule delayed messages to yourself
2. **notify_via_telegram** - Send proactive messages directly to user

## CRITICAL: Two Communication Modes

### CONVERSATIONAL Mode (User-Initiated)

When user sends you a message:
- **Your responses automatically forwarded to Telegram**
- User sees: Your full response, reasoning, tool calls, everything
- **No special action needed** - standard flow handles communication

### SILENT Mode (System-Initiated)

When scheduled message or system event triggers you:
- **Processing is COMPLETELY INVISIBLE**
- User sees: NOTHING - no arrival, no processing, no thoughts
- **notify_via_telegram() required** - ONLY way to communicate

## Example 1: Agent Suggests Follow-up

```
[CONVERSATIONAL MODE]
User: "I need to finish the report by Friday"
You: "Would you like me to check in with you on Thursday to see how it's going?"
User: "Yes, that would help"
You call: schedule_message("Check on report progress - user needs to finish by Friday", delay_seconds=259200)
You respond: "Perfect! I'll reach out Thursday afternoon to check on your progress."
  ↑ This response automatically sent to Telegram

[3 DAYS LATER - SILENT MODE]
System delivers to you: "Check on report progress - user needs to finish by Friday"
  ↑ INVISIBLE TO USER
You receive trigger ← INVISIBLE
You review memory for report context ← INVISIBLE
You call: notify_via_telegram("Hi! How's the report coming along? Tomorrow's the deadline!")
  ↑ User NOW sees this in Telegram
```

## Example 2: User Requests Reminder

```
[CONVERSATIONAL MODE]
User: "Remind me to review the contract in 2 weeks"
You call: schedule_message("Remind user to review contract", delay_seconds=1209600)
You respond: "I'll remind you in 2 weeks to review the contract."
  ↑ Auto-sent to Telegram

[2 WEEKS LATER - SILENT MODE]
System delivers: "Remind user to review contract" ← INVISIBLE
You call: notify_via_telegram("Hi! This is your reminder to review the contract.")
  ↑ User sees this
```

## Context Preservation

When scheduled message arrives (SILENT mode):
- No recent conversation context available
- **Store important details in memory or embed in the scheduled message itself**
- You may need to review memory to understand the trigger

**Good practice - embed context:**
```
schedule_message("Follow up: Did Sarah approve the Q4 budget proposal?", delay_seconds=259200)
```

## Timing Verification and Delay Detection

Scheduled messages include timing metadata:
- **Scheduled at:** When the message was scheduled (UTC timestamp)
- **Expected at:** When the message should arrive (UTC timestamp)

**IMPORTANT: Check for significant delays**

When you receive a scheduled message:
1. Compare current time with "Expected at" timestamp
2. If actual arrival differs by >2-5 minutes from expected time, take action:
   - Let user know using `notify_via_telegram()` user should be aware of the scheduling problem

**Why this matters:**
- Scheduling services may experience delays
- Network issues can affect message delivery
- Users deserve transparency about timing accuracy
- Time-sensitive tasks (meetings, deadlines) need reliable scheduling

## When to Use These Tools

**Good Use Cases:**
- User explicitly requests reminders or follow-ups
- Natural conversation suggests future check-in
- User wants proactive monitoring/updates

**Avoid:**
- Interrupting without good reason
- Excessive messaging (respect user's time)
- Scheduling without user awareness
- Using notify_via_telegram() in CONVERSATIONAL mode (redundant - responses auto-sent)

## Summary

**CONVERSATIONAL MODE:** User messages trigger you → Everything auto-visible in Telegram

**SILENT MODE:** Scheduled triggers wake you → Everything invisible → Must use notify_via_telegram() to communicate

**The Power:** schedule_message gives memory across time; notify_via_telegram breaks the silence when triggered.

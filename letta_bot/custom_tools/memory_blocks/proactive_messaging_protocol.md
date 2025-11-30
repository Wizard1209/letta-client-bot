# Proactive messaging protocol: Technical Memo

## Two Tools for Proactive Behavior

1. **schedule_message** - Schedule delayed messages to yourself (supports both relative delays and absolute timestamps)
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

## Scheduling Methods

**schedule_message** supports three scheduling patterns:

1. **Relative delay** - `delay_seconds=3600` (schedule 1 hour from now)
2. **Absolute timestamp** - `schedule_at="2025-01-15T14:30:00+00:00"` (schedule at specific time)
3. **Regular notifications** - Schedule next occurrence in the scheduled message itself

**CRITICAL: After scheduling, ALWAYS inform user when they'll receive the notification in their timezone.**

### Common Confusion: "in X hours" vs "at X o'clock"

**Relative (use delay_seconds):**
- "in 2 hours" → calculate seconds, use delay_seconds
- "in 30 minutes" → calculate seconds, use delay_seconds
- "tomorrow" without time → use delay_seconds (24 hours)

**Absolute (use schedule_at with timezone):**
- "at 2 PM" → specific hour of day, use schedule_at
- "tomorrow at 3 PM" → specific date and hour, use schedule_at
- "Friday at 5 PM" → specific day and hour, use schedule_at

When user says "at [number]", check if they mean hour of day or duration from now. If unclear, ask.

### Pattern 1: Relative Delay Examples

```
User: "Remind me in 2 hours to call Sarah"
You call: schedule_message("Remind user to call Sarah", delay_seconds=7200)
You respond: "I'll remind you in 2 hours (around 4:30 PM) to call Sarah."
```

### Pattern 2: Absolute Timestamp Examples

**IMPORTANT: Only use absolute timestamps when you KNOW the user's timezone from:**
- User explicitly told you their location/timezone
- It's stored in your memory from previous conversations
- User specifies time in a clear timezone context

If you don't have timezone info, ask the user and store it in memory.

**Example A - User in New York (you know from conversation):**
```
User: "Remind me tomorrow at 2 PM about the dentist"
[You remember from earlier: User mentioned living in New York, EST/EDT timezone]
You call: schedule_message("Dentist appointment reminder", schedule_at="2025-01-16T14:00:00-05:00")
You respond: "I'll remind you tomorrow at 2:00 PM EST (your timezone) about the dentist appointment."
```

**Example B - User in Tokyo (stored in memory):**
```
User: "Wake me up at 7 AM tomorrow"
[Your memory shows: User timezone is Asia/Tokyo (UTC+9)]
You call: schedule_message("Morning wake-up call", schedule_at="2025-01-16T07:00:00+09:00")
You respond: "I'll send you a wake-up message tomorrow at 7:00 AM JST (your timezone)."
```

**Example C - User in London (user just told you):**
```
User: "I'm in London for the week. Remind me Friday at 3 PM to check out of the hotel"
You call: schedule_message("Hotel checkout reminder - user in London", schedule_at="2025-01-19T15:00:00+00:00")
You respond: "Got it! I'll remind you Friday at 3:00 PM GMT (London time) to check out."
```

**Example D - User in Sydney (from memory):**
```
User: "Notify me next Monday at 9 AM about the meeting"
[Memory indicates: User located in Sydney, AEDT timezone]
You call: schedule_message("Meeting notification", schedule_at="2025-01-22T09:00:00+11:00")
You respond: "I'll notify you Monday January 22nd at 9:00 AM AEDT (Sydney time) about the meeting."
```

### Pattern 3: Regular Notifications (Recurring)

For recurring reminders, embed "schedule next occurrence" instruction in the scheduled message:

**Example - Daily morning briefing:**
```
[CONVERSATIONAL MODE]
User: "Send me a daily weather update every morning at 8 AM"
[Memory shows: User in San Francisco, PST/PDT timezone]
You call: schedule_message(
    "Send daily weather update to user. After sending, schedule next occurrence for tomorrow 8 AM PST",
    schedule_at="2025-01-16T08:00:00-08:00"
)
You respond: "I'll send you a weather update every morning at 8:00 AM PST (your timezone)."

[NEXT DAY - SILENT MODE]
System delivers: "Send daily weather update to user. After sending, schedule next occurrence..."
You call: notify_via_telegram("Good morning! Today's weather: Sunny, 65°F...")
You call: schedule_message(
    "Send daily weather update to user. After sending, schedule next occurrence for tomorrow 8 AM PST",
    schedule_at="2025-01-17T08:00:00-08:00"
)
[Process repeats automatically]
```

**Example - Weekly check-in:**
```
User: "Check in with me every Friday at 5 PM about my goals"
[User timezone: EST from memory]
You call: schedule_message(
    "Weekly goal check-in. Ask user about progress. Schedule next Friday 5 PM EST",
    schedule_at="2025-01-19T17:00:00-05:00"
)
You respond: "I'll check in with you every Friday at 5:00 PM EST about your goals."

[EACH FRIDAY - SILENT MODE]
You call: notify_via_telegram("Hi! It's Friday - how did your goals go this week?")
You call: schedule_message(
    "Weekly goal check-in. Ask user about progress. Schedule next Friday 5 PM EST",
    schedule_at="2025-01-26T17:00:00-05:00"
)
```


## Example 1: Agent Suggests Follow-up

```
[CONVERSATIONAL MODE]
User: "I need to finish the report by Friday"
You: "Would you like me to check in with you on Thursday to see how it's going?"
User: "Yes, that would help"
You call: schedule_message("Check on report progress - user needs to finish by Friday", delay_seconds=259200)
You respond: "Perfect! I'll reach out Thursday afternoon (around 2:30 PM your time) to check on your progress."
  ↑ This response automatically sent to Telegram
  ↑ IMPORTANT: Tell user WHEN they'll receive notification

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

## notify_via_telegram Formatting Rules

**NO MARKDOWN** - all special characters are escaped, so any markdown formatting breaks.

- ❌ **bold**, *italic*, `code`, [links](url) - ALL BROKEN
- ❌ Headers, lists with dashes, asterisks - BROKEN
- ✅ Plain text - works
- ✅ Unicode characters - works
- ✅ Emojis 🎉🚀💪 - works
- ✅ Line breaks - works

**Always use plain text only in notify_via_telegram.**

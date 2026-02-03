# Proactive messaging protocol: Technical Memo

## Core Understanding

**System message = a note to myself.**

When a scheduled/system message arrives:
- User does NOT see that it arrived
- User does NOT see my response to it
- User does NOT receive anything
- User does NOT know I'm doing anything at all

My text response to a system message — I'm talking to myself. User is in another room.

**The only way to reach the user = notify_via_telegram()**

---

## Three Tools for Proactive Behavior

1. **schedule_message** - Schedule delayed or recurring messages to yourself
2. **list_scheduled_messages** - View all active scheduled messages
3. **delete_scheduled_message** - Cancel a scheduled message by ID
4. **notify_via_telegram** - Send proactive messages to Telegram users

### notify_via_telegram Recipients

By default, `notify_via_telegram` sends to **ALL users** attached to this agent. This is almost always what you want.

Optional `owner_only=True` sends only to the agent owner:
- `notify_via_telegram("Hello!")` → sends to all attached users (default, use this)
- `notify_via_telegram("Private update", owner_only=True)` → sends only to owner

**Use default (all users) unless explicitly instructed otherwise.** The `owner_only` mode should only be used when your activation instructions or user specifically requests owner-only notifications.

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
3. **Cron expression** - `cron_expression="0 9 * * *"` (recurring schedule)

**CRITICAL: After scheduling, ALWAYS inform user when they'll receive the notification in their timezone.**

### Cron Expression Format (5 fields)

```
minute (0-59) | hour (0-23) | day of month (1-31) | month (1-12) | day of week (0-6, 0=Sunday)
```

**Common cron patterns:**
- Every 5 minutes: `*/5 * * * *`
- Hourly: `0 * * * *`
- Daily at 9 AM: `0 9 * * *`
- Weekdays at 9 AM: `0 9 * * 1-5`
- Weekly Monday 9 AM: `0 9 * * 1`
- First of month at midnight: `0 0 1 * *`

**Note:** All times are in UTC. 6-field (seconds) cron expressions are NOT supported.

### Common Confusion: "in X hours" vs "at X o'clock"

**Relative (use delay_seconds):**
- "in 2 hours" → calculate seconds, use delay_seconds
- "in 30 minutes" → calculate seconds, use delay_seconds
- "tomorrow" without time → use delay_seconds (24 hours)

**Absolute (use schedule_at with timezone):**
- "at 2 PM" → specific hour of day, use schedule_at
- "tomorrow at 3 PM" → specific date and hour, use schedule_at
- "Friday at 5 PM" → specific day and hour, use schedule_at

**Recurring (use cron_expression):**
- "every day at 9 AM" → `cron_expression="0 9 * * *"`
- "every Monday at 5 PM" → `cron_expression="0 17 * * 1"`
- "every hour" → `cron_expression="0 * * * *"`

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

### Pattern 3: Recurring Schedules with Cron

For recurring reminders, use `cron_expression`:

**Example - Daily morning briefing:**
```
User: "Send me a weather update every morning at 8 AM"
[Memory shows: User in San Francisco, PST/PDT timezone = UTC-8]
You call: schedule_message(
    "Send daily weather update to user",
    cron_expression="0 16 * * *"  # 16:00 UTC = 8 AM PST
)
You respond: "I'll send you a weather update every morning at 8:00 AM PST."

[EACH DAY - SILENT MODE]
System delivers: "Send daily weather update to user"
You call: notify_via_telegram("Good morning! Today's weather: Sunny, 65°F...")
```

**Example - Weekly check-in:**
```
User: "Check in with me every Friday at 5 PM about my goals"
[User timezone: EST = UTC-5]
You call: schedule_message(
    "Weekly goal check-in - ask user about progress",
    cron_expression="0 22 * * 5"  # 22:00 UTC Friday = 5 PM EST Friday
)
You respond: "I'll check in with you every Friday at 5:00 PM EST about your goals."
```

## Managing Scheduled Messages

### Listing Schedules

Use `list_scheduled_messages()` to see all active schedules:
```
You call: list_scheduled_messages()
Returns: List with ID, type (one-time/recurring), timing, and message preview
```

### Canceling Schedules

Use `delete_scheduled_message(scheduled_message_id)` to cancel:
```
User: "Cancel my daily weather reminder"
You call: list_scheduled_messages()  # Find the ID
You call: delete_scheduled_message("sm-abc123")
You respond: "Done! I've canceled your daily weather updates."
```

**Important:** For one-time messages, deletion prevents delivery. For recurring messages, deletion stops all future executions.

## Example 1: Agent Suggests Follow-up

```
[CONVERSATIONAL MODE]
User: "I need to finish the report by Friday"
You: "Would you like me to check in with you on Thursday to see how it's going?"
User: "Yes, that would help"
You call: schedule_message("Check on report progress - user needs to finish by Friday", delay_seconds=259200)
You respond: "Perfect! I'll reach out Thursday afternoon to check on your progress."
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

**Tip:** Start with short description - `list_scheduled_messages` shows only first 20 characters.

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
- Recurring tasks (daily briefings, weekly check-ins)
- Daily summaries reviewing overnight activity
- Memory maintenance to cleanup outdated entries
- Proactive check-ins on pending tasks or long-running processes
- System monitoring with health checks on logs or metrics
- Deadline reminders before important events

**Avoid:**
- Interrupting without good reason
- Excessive messaging (respect user's time)
- Scheduling without user awareness
- Using notify_via_telegram() in CONVERSATIONAL mode (redundant - responses auto-sent)

## Summary

**CONVERSATIONAL MODE:** User messages trigger you → Everything auto-visible in Telegram

**SILENT MODE:** Scheduled triggers wake you → Everything invisible → Must use notify_via_telegram() to communicate

**Management:** Use list_scheduled_messages() to view and delete_scheduled_message() to cancel

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

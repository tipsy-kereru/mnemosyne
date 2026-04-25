# Daily Life Domain Schema

## Entity Types

```yaml
task:
  description: "Action item or to-do with deadline and priority"
  properties:
    - title
    - deadline
    - priority: [high, medium, low]
    - status: [pending, in_progress, completed]
    - recurring: boolean
    - context: string  # location or situation

person:
  description: "Human contact with relationship and interaction history"
  properties:
    - name
    - role: [family, friend, colleague, professional, acquaintance]
    - contact: {email, phone, address}
    - last_interaction: datetime
    - preference: string  # communication style

place:
  description: "Physical or virtual location"
  properties:
    - name
    - type: [home, work, public, online]
    - address: string
    - visit_frequency: string
    - associated_tasks: [task_id]

event:
  description: "Calendar event or appointment"
  properties:
    - title
    - datetime
    - duration
    - participants: [person_id]
    - location: place_id
    - reminder: duration

habit:
  description: "Recurring behavior pattern"
  properties:
    - name
    - frequency: [daily, weekly, monthly]
    - time: string
    - completion_history: [datetime]
    - streak: integer

preference:
  description: "User preference or setting"
  properties:
    - category: [food, travel, entertainment, shopping, work]
    - value: string
    - confidence: float  # 0-1 certainty

note:
  description: "General reference note"
  properties:
    - title
    - content
    - tags: [string]
    - links: [entity_id]
```

## Relationship Types

```yaml
# Task relationships
task.assigned_to: person
task.located_at: place
task.part_of: project  # parent task

# Person relationships
person.interacts_with: person
person.knows_via: event
person.mentioned_in: note

# Temporal patterns
event.followed_by: event
habit.supports: goal
task.blocks: task  # dependency
```

## Extraction Rules

1. **Emails/Messages**: Extract `person`, `task`, `deadline`
2. **Calendar**: Extract `event`, `person`, `place`
3. **Notes**: Extract `note`, `preference`, `habit`
4. **Documents**: Extract `place`, `event`, `person`
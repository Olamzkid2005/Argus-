# Google Stitch Functional Prompt - Argus SOC Platform

## Overview
Create a cybersecurity operations center dashboard for vulnerability assessment and threat intelligence. This platform enables security teams to initiate security scans, monitor findings, manage assets, and collaborate on remediation.

## Platform Structure

### Core Features

#### 1. Landing Page
- Hero section with platform introduction
- Feature showcase highlighting core capabilities
- Call-to-action for authentication and signup
- Footer with navigation links

#### 2. Authentication
- Sign-in page with email/password authentication
- Sign-up page for new user registration
- Session management with NextAuth
- Protected routes for authenticated users

#### 3. Dashboard (Main Intelligence Hub)
- Real-time engagement monitoring via WebSocket
- Engagement connection/disconnection controls
- Statistics overview: total findings, engagements, critical issues, verified findings
- Network intelligence feed showing live vulnerability discoveries
- Execution timeline displaying scan progress and state transitions
- Recent engagements list with quick access
- Scanner activity panel showing tool execution steps
- Attack path visualization
- Tool performance metrics
- State management: created, awaiting_approval, scanning, complete, failed

#### 4. Engagements (Scan Initiation)
- Create new security assessments
- Two scan types: Web Application (URL) and Repository (code)
- Target identifier input
- Scan aggressiveness configuration: Default, High, Extreme
- Authorization scope validation
- Progress tracking during initialization
- Redirect to dashboard for live monitoring

#### 5. Findings (Vulnerability Management)
- Comprehensive vulnerability listing
- Severity filtering: Critical, High, Medium, Low, Info
- Search functionality by pattern, endpoint, or identifier
- Engagement filtering
- AI-powered vulnerability explanations
- Attack chain analysis showing how vulnerabilities can be combined
- Evidence/POC display with code blocks
- Verification workflow
- Finding deletion
- Confidence scores
- Source tool attribution
- Expandable details panel

#### 6. Analytics
- Vulnerability discovery trends over time
- Date range filtering: 7 days, 30 days, 90 days
- Severity distribution visualization
- Engagement comparison metrics
- Scheduled report management
- Email report delivery
- Report types: Summary, Executive, Detailed, Comparative
- Frequency options: Daily, Weekly, Monthly, Quarterly

#### 7. Reports
- Report generation and management
- Report types: Engagement, Finding, Summary, Executive
- Format options: PDF, HTML, JSON
- Status tracking: Generating, Ready, Failed
- Download functionality
- Share capability
- Report deletion
- Type-based filtering
- Search functionality

#### 8. Collaboration
- Team management with role-based access (Admin, Member, Viewer)
- Team member invitation
- Finding comments and discussions
- Assignment workflow for vulnerability remediation
- Priority and due date management
- Approval workflows for scan authorization
- Activity feed showing all platform actions
- Notification system with unread tracking
- Mark all as read functionality

#### 9. Settings
- OpenRouter API key configuration for AI features
- AI model selection from multiple providers (Anthropic, OpenAI, Google, Meta, DeepSeek, Mistral, Qwen, NVIDIA, Perplexity)
- Custom model ID input
- Scan aggressiveness presets with detailed tool configurations
- Session logout
- Security notices

#### 10. Rules (Custom Detection Rules)
- Custom vulnerability detection rule creation
- Rule YAML editor
- Severity assignment
- Category classification
- Version management
- Status tracking: Active, Draft, Deprecated
- Community sharing option
- Rule filtering by status

#### 11. Assets (Asset Inventory)
- Asset registration and management
- Asset types: Domain, IP, Endpoint, Repository, Container, API
- Risk scoring and level assignment
- Criticality classification
- Lifecycle status: Active, Inactive, Decommissioned
- Verification tracking
- Last scanned timestamps
- Type-based filtering
- Statistics overview

### Technical Components

#### Navigation
- Sidebar navigation with main menu items
- Active state indication
- Command palette for quick navigation (Cmd+K)
- Theme toggle: Light, Dark, System
- User profile section

#### Real-time Features
- WebSocket connections for live engagement monitoring
- Scanner activity polling from database
- Finding discovery notifications
- State transition updates

#### Data Visualization
- Charts for trends and distributions
- Attack path graphs
- Execution timelines
- Performance metrics

#### Special Effects
- Matrix data rain animation
- Surveillance eye visualization
- Scanner reveal effects
- These provide visual feedback for monitoring states

### Data Models

#### Engagement
- ID, target URL, scan type, aggressiveness
- Status workflow states
- Authorization scope
- Created timestamp
- Findings count

#### Finding
- ID, type, severity, endpoint
- Source tool attribution
- Verification status
- Confidence score
- Evidence data
- AI explanation
- Created timestamp

#### Asset
- ID, asset type, identifier
- Display name, description
- Risk score and level
- Criticality
- Lifecycle status
- Verification status
- Discovered and last scanned timestamps

#### Rule
- ID, name, description
- Severity, category
- Rule YAML definition
- Status, version
- Community sharing flag

#### Team Member
- ID, user ID, email, name
- Team role
- Invitation status
- Created timestamp

#### Assignment
- ID, finding ID
- Assigned to user
- Status, priority
- Due date
- Assigned by

#### Approval Request
- ID, workflow name and type
- Status
- Requester
- Engagement target
- Notes

#### Activity/Notification
- ID, type
- Title, message
- Read status
- Created timestamp
- User attribution

#### Scheduled Report
- ID, name
- Report type, frequency
- Email recipients
- Active status
- Next run timestamp

### User Settings
- OpenRouter API key
- Preferred AI model
- Default scan aggressiveness

### Key Workflows

1. **Engagement Creation**: User selects target and aggressiveness → System validates → Engagement created → User approves → Scan initiates → Real-time monitoring in dashboard

2. **Finding Analysis**: Vulnerabilities discovered → User can request AI explanation → Attack chain analysis available → Findings can be verified → Assignments created for remediation

3. **Report Generation**: User selects report type and parameters → Report queued → Generation completes → Report available for download or email delivery

4. **Team Collaboration**: Team members invited → Assignments distributed → Comments added to findings → Approval workflows for sensitive operations → Activity feed tracks all actions

5. **Asset Management**: Assets discovered during scans or added manually → Risk assessed → Lifecycle tracked → Verification status maintained

6. **Custom Rules**: Users create YAML-based detection rules → Rules categorized and versioned → Rules can be shared with community → Rules used in future scans

### Integration Points
- OpenRouter API for AI-powered vulnerability explanations
- Email service for report delivery
- Database for persistent storage
- Redis for real-time caching
- PostgreSQL for structured data
- WebSocket server for live updates

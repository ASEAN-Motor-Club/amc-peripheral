# Motor Town — Motorpedia (In-Game Help/Encyclopedia)

The game's built-in guide articles (`Helps` DataTable). Each entry is a topic 
the bot can be asked about. When a question matches one of these topics, 
return the full article text below. Rich-text tags are already converted to markdown;
 `[image: <id>]` marks an inline game image the bot cannot render.

## Cargo Payment Scaling

Most of the cargo delivery payments are scaled based on the vehicle's capacity.
Large vehicles still earn more when full, but small vehicles can be beneficial when you deliver a few items.

**Example of Cargo payment table**
Small Truck: Capacity(1), Payment Per Cargo(1000), Total Payment(1000)
Medium Truck: Capacity(4), Payment Per Cargo(500), Total Payment(2000)
Large Truck: Capacity(16), Payment Per Cargo(250), Total Payment(4000)

---

## Overload

**Vehicle Weight Regulation**
GVW(Gross Vehicle Weight) should not exceed **40 tons**
Axle weight should not exceed **10 tons**

There are Weight-In-Motion systems on some roads which detect vehicle weight and fine the driver.

[image: Help_Overload_WIM]

---

## Town Status

You can get a bonus payment by increasing the town resident population

1. Open World Map and check the 'Town' filter to see each Town's borders
2. Each town has a Supermarket and supplying food to them will increase the population up to 100%
3. Transporting bus passengers will increase the  population of passenger's home or working place town up to 100%
4. Police patrol will increase the town population by up to 20%
5. Garbage collection increases town population by up to 20%

Any job in each town will get a bonus payment for population increase x 0.2, up to 30%
(ex: If the population is increased by 50%, you get a 10% bonus. If the population is increased by 150% or more, you get a 30% bonus)

---

## Escort

When someone is transporting oversize cargo, an Escort Job becomes available.
To take on an Escort Job, you must equip the Oversize Escort License part, accept the job through the in-game menu, and closely escort the vehicle until it reaches its destination.

---

## Supply and Demand

**Supply and Demand Pricing**
Delivery payments change dynamically based on supply and demand at each location.
**High Supply**
When the source has **plenty of stock**, delivery pay increases.
**High Demand**
When the destination has **low inventory**, delivery pay increases.
Deliver goods from well-stocked sources to destinations that need them most for higher rewards.
You can check current demand rates on the **Delivery Board** before accepting jobs.

---

## Fragile & Time-Limited Cargo

**Fragile Cargo**
Some cargo types like **Furniture** take damage from collisions and rough driving.
Drive carefully to deliver them in good condition.
**Time-Limited Cargo**
Certain cargo like **Food** and **Concrete** must be delivered within a time limit.
Delivering on time earns a bonus, while exceeding the time limit results in reduced pay or delivery failure.
A timer is displayed on the HUD during these deliveries.

---

## Drive Mode

**Drive Modes**
You can switch between drive modes when the vehicle is stopped or at low speed.
**Comfort** - Stable handling with understeer bias. Ideal for safe driving and deliveries.
**Sport** - Responsive steering with faster handling. Better for skilled drivers.
**Drift** - Stability control is relaxed, making it easier to initiate and maintain drifts.

---

## Fuel Management

**Fuel System**
Vehicles consume fuel based on speed and engine power. When fuel reaches 0, the vehicle stops.
**Refueling**
Drive to a **Gas Station** and interact with the fuel pump.
Fuel cost is deducted from your personal or company account.
The fuel gauge on the dashboard shows remaining fuel. A warning appears when fuel is low.

---

## Job Levels

**Job Level System**
Each job type has its own experience level. Gain XP by completing job-related activities.
**Driver** - General driving, hitchhiking
**Taxi** - Taxi passenger pickups and deliveries
**Bus** - Bus route operations
**Truck** - Cargo deliveries
**Racer** - Driving on tracks, drifting
**Wrecker** - Towing missions
**Police** - Arrests and patrol completions
Level up to unlock new vehicles.

---

## Police & Violations

**Traffic Violations & Fines**
Speeding: **$100** | Collision: **$100** | Wrong Way: **$100**
Refuse to Stop: **$300** | Vehicle Theft: **$2,000** | Crime: **$3,000**
All violations are recorded until you are caught or surrender. Fines stack.
**Police Chase**
If you do not stop and continue to flee, you will be marked as a fleeing suspect.
**Player police officers** can deploy **Spike Strips** to stop fleeing vehicles. Spike strips only affect fleeing suspects.
**Surrender**
You can surrender voluntarily, but not while in a police car, during a Getaway, or in a stolen vehicle.

---

## Fire Fighting

**Fire Fighting Flow**
1. **Spot** a fire by observing it, or wait for large fires to be auto-reported
2. **Accept** the fire job from the Fire Job panel
3. **Extinguish** using water spray, fire hose, or fire extinguisher
4. When the fire is fully extinguished, the mission is **complete**
**Rewards**
Bonuses increase with distance from roads and fire stations, and with fire size.
The first team to begin extinguishing receives an additional first responder bonus.
**Co-op**
Total reward increases with more participants. Rain also helps cool fires.

---

## Bus Driver

**Bus Driver Job**
Run bus routes, picking up and dropping off passengers at bus stops.
**Requirements**
- Equip the **Bus License** part on your vehicle
- Own a Bus type vehicle
**How to Play**
1. Select a route (company route or public route)
2. Drive along the route, stopping at each bus stop for passenger boarding and alighting
3. Continue operating or end the job from the Bus Job menu at any time
**Payment** = Passengers x Route Fare
Earns **Bus Driver EXP**.

---

## Taxi Driver

**Taxi Driver Job**
Accept passenger calls and drive them to their destinations.
**Requirements**
- Equip the **Taxi License** part
- Own a passenger vehicle
**How to Play**
1. Enable taxi standby mode
2. Receive and accept a passenger call
3. Pick up the passenger at their location
4. Drive to the destination and drop off
**Passenger Types**
- Normal: Standard fare
- Emergency (hospital): Time bonus available
- Comfort: Premium fare
Payment is based on distance. Earns **Taxi EXP**.

---

## Towing & Winch

**Towing System**
Connect and tow broken-down vehicles or trailers using different methods.
**Connection Types**
- **Trailer Hitch**: For small trailers and caravans. Requires TrailerHitch part.
- **5th Wheel**: For semi-trailer connections with semi-tractors.
- **Winch**: Wire-based towing for recovery. Requires Winch part.
**Winch Self-Recovery**
If stuck offroad, attach the winch to a tree or rock as an anchor point, then use the winch to pull your vehicle free.
**Caution**
Excessive speed or sharp turns while towing may disconnect the link.
Earns **Wrecker EXP**.

---

## Company Basics

**Company System**
Create and manage your own transportation company.
**Company vs Corporation**
- Company: Available in all environments.
- Corporation: Dedicated server only. Starts with initial capital.
**Roles**
- **Owner**: Full control over all company operations
- **Manager**: Vehicle assignment, route management
- **Apprentice Driver**: Default role for new members. Basic delivery and driving
A player can only belong to one company at a time.

---

## Company AI Drivers

**AI Driver System**
Assign AI drivers to company vehicles to earn revenue automatically.
**Setup**
1. Register a vehicle and equip the required license part
2. Assign a bus route, truck route, or taxi depot
3. Activate the AI driver
**Profit Share**
A percentage of AI vehicle revenue is deposited into the company account. Rates vary by job type.
**Running Costs**
Vehicles incur periodic operating costs (fuel, wear, seats).
Damaged vehicles cost more to operate. At **0% condition**, AI vehicles can no longer take on jobs.
Daily reports summarize profit/loss per vehicle.

---

## Town Policy

**Trade Balance & Town Policy**
The town accumulates **Trade Balance** from export activities and loses it from imports.
**Policies**
Activate town-wide policies using trade balance. Each policy has an hourly cost.
Policies are **only active when trade balance > 0**. If balance drops to 0 or below, all policy effects are immediately disabled.
**Policy Effects**
- Fuel Subsidy: Reduced fuel costs
- Max Vehicle Length / Cargo Height increase
- Company Profit Share multiplier
- Vehicle Condition decay speed reduction
**Readiness**
Newly purchased policies may require preparation time before effects activate.

---

## Weather Effects

**Weather System**
Weather affects driving conditions.
**Rain**
- **Reduced tire grip** and longer braking distances
- **Reduced visibility**
- Helps cool down active fires
**Time of Day**
- Daytime: Standard visibility
- Twilight: Glare effects, limited visibility
- Night: **Headlights required**, reduced visibility
The server host can adjust rain intensity, fire frequency, and time progression speed.

---

## Housing

**Housing System**
Own properties in the game world. On dedicated servers, rental is also available.
**Purchase**
Buy houses from designated real estate locations. Customize anytime after purchase.
**Building Placement**
Use **Building Blueprint** items to place structures. Placement validates collision, terrain, and zone restrictions.
Green preview = valid, Red preview = invalid.
Some buildings require delivering construction materials before they can be completed.
**Company Depot**
Build a company depot on your property. Depots can be added to company vehicle routes, automatically recover vehicle **condition**, and serve as a **taxi dispatch base**.

---

## Drone

**Drone System**
Deploy a drone item to fly and scout from the air.
**Flight Modes**
- **Normal**: Stable hovering, slower speed
- **Sport**: Faster speed, more responsive controls
**Limitations**
- Limited **battery life** (flight time)
- Limited **operating range** from the operator
- Exceeding limits causes auto-return or crash
**Uses**
- Scout delivery routes in advance
- Search for hidden vehicles and costumes
- **Search and Rescue**: Locate patients in the field
- **Fire Surveillance**: Monitor and spot fires from above
- Guide teammates during co-op play

---

## Oversize Cargo

**Oversize Cargo Transport**
Some large cargo is flagged as **Oversize** and requires extra care during transport.
Oversize cargo is larger than standard loads, so pay attention to clearance and turning radius.
**Escort Connection**
When you transport oversize cargo, an **Escort Job** becomes available for other players.
Escort vehicles must equip the Escort License part and stay within range to earn escort rewards.
Oversize deliveries generally pay more due to the added difficulty of handling large loads.

---

## Wrecked Vehicle Tow Requests

**Responding to Tow Requests**
When you accept a tow request, you can **reject the job** if the vehicle is too damaged to handle safely.

**Check First**
Inspect the target vehicle's condition before committing. Wrecked vehicles may require extra equipment such as the **winch** or careful tow-bar handling.

Rejecting a job does not penalize you — another wrecker can pick it up.

---

#include "../deploy/goto_ramp.hpp"
#include <cassert>
#include <cmath>
#include <iostream>

struct Point {
    double x, y, z;
};

double distance(const Point& a, const Point& b) {
    return std::sqrt((a.x - b.x) * (a.x - b.x) +
                     (a.y - b.y) * (a.y - b.y) +
                     (a.z - b.z) * (a.z - b.z));
}

void testVariableTickIntervals() {
    const Point start{1.0, -2.0, 0.5};
    const Point goal{2.0, 0.0, 2.5};
    Point command = start;
    const double intervals[] = {0.002, 0.017, 0.05, 0.083, 0.004};
    double elapsed = 0.0;
    bool arrived = false;
    int ticks = 0;
    while (!arrived && ticks < 2000) {
        const double dt = intervals[ticks % 5];
        const Point previous = command;
        arrived = goto_motion::advancePosition(command, goal, 0.5, dt);
        elapsed += dt;
        assert(distance(previous, command) <= 0.5 * dt + 1e-12);
        assert(distance(command, goal) <= distance(previous, goal));
        assert(std::abs((command.y - start.y) - 2.0 * (command.x - start.x)) < 1e-12);
        assert(std::abs((command.z - start.z) - 2.0 * (command.x - start.x)) < 1e-12);
        if (elapsed < 6.0 - 1e-10) assert(!arrived);
        ++ticks;
    }
    assert(arrived && elapsed >= 6.0 && elapsed < 6.083 + 1e-10);
    assert(command.x == goal.x && command.y == goal.y && command.z == goal.z);
    assert(goto_motion::advancePosition(command, goal, 0.5, 0.0));
    assert(command.x == goal.x && command.y == goal.y && command.z == goal.z);
}

void testStallAndDeadline() {
    Point command{0.0, 0.0, 0.0};
    const Point goal{0.0, -1.0, 0.0};
    assert(!goto_motion::advancePosition(command, goal, 0.5, 10.0));
    assert(std::abs(command.y + 0.05) < 1e-12);
    // Repeated ticks at the same deadline must not spend the stalled time again.
    const Point after_stall = command;
    for (int i = 0; i < 10; ++i) {
        assert(!goto_motion::advancePosition(command, goal, 0.5, 0.0));
        assert(distance(command, after_stall) == 0.0);
    }
    assert(!goto_motion::advancePosition(command, goal, 0.5, -1.0));
    assert(distance(command, after_stall) == 0.0);
    assert(!goto_motion::advancePosition(command, goal, 0.5, 0.02));
    assert(std::abs(command.y + 0.06) < 1e-12);
}

void testEndpointInsideArrivalTolerance() {
    Point command{0.0, 0.0, 0.0};
    const Point goal{0.09, 0.0, 0.0};
    assert(!goto_motion::advancePosition(command, goal, 0.5, 0.1));
    assert(command.x == 0.05);
    assert(goto_motion::advancePosition(command, goal, 0.5, 0.1));
    assert(command.x == goal.x && command.y == goal.y && command.z == goal.z);
    Point stationary = goal;
    assert(goto_motion::advancePosition(stationary, goal, 0.5, 0.0));
    assert(distance(stationary, goal) == 0.0);
}

int main() {
    testVariableTickIntervals();
    testStallAndDeadline();
    testEndpointInsideArrivalTolerance();
    std::cout << "GoTo ramp tests passed\n";
}

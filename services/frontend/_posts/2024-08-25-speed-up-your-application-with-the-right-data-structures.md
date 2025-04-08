---
layout: post
title: Speed Up Your Application with the Right Data Structures
date: "2024-08-25"
categories: 
  - "Data Structures"
  - "Algorithms"
tags: 
  - "data structures"
  - "algorithms"
readtime: true
lang: en
---

> ⚡️ **TL;DR**  
> In this post, we explore the importance of selecting the right data structures to enhance the performance of your applications. We'll discuss how different data structures can impact efficiency and provide examples to illustrate their use.

Let's dive into the importance of data structures and how the selection of the right data structure can make a huge difference in the performance of your application.  

Let's start with the basics. When we start any piece of software development, we want to make things work, and later we focus on making things work efficiently. Data structures play a crucial role in making things work efficiently.

For example, let's say we need to write a routine to print odd numbers from 1 to 100. We can write a simple loop to iterate from 1 to 100 and print the odd numbers. But what if we need to print odd numbers from 1 to 1 million? The simple loop will work, but it will be slow. We can make it faster by using the right data structure.

```go
func printOddNumbers() {
    for i := 1; i <= 1000000; i++ {
        if i%2 != 0 {
            fmt.Println(i)
        }
    }
}
```

On the other hand, if we decide to only iterate one out of every two numbers, we can use a different data structure to make it faster.

```go
func printOddNumbers() {
    for i := 1; i <= 1000000; i += 2 {
        fmt.Println(i)
    }
}
```

Essentially the efficiency of a program is directly related to the speed and the speed can be translated on how many steps it takes to complete a task. Not on how long it takes to complete a task. The reason is because we don't know the hardware resources that will be available to run our program. So, we can't say that a program is efficient because it runs in 1 second. We can say that a program is efficient because it takes 100 steps to complete a task. Speed is also known as time complexity and the number of steps is known as space complexity.

Now, let's talk about the importance of data structures focusing on two: arrays and sets. We will evaluate the basic operations of these two data structures and see how they perform.

### Arrays

Arrays are a collection of elements that are stored in contiguous memory locations. Until now, we have been using arrays to store data. Arrays are simple and easy to use.

How do we use arrays? Basically four operations: read, search, insert and delete. Let's see how these operations perform in arrays.

- Reading: Reading an element means that a variable allocates a contiguous set of empty cells in a memory block. The computer only needs to know the memory address of the first cell to access the entire block. This operation takes only 1 step since the computer knows the memory address of the first cell.

- Searching: Searching an element is the opposite of reading. The computer needs to iterate through the entire array to find the element since the computer doesn't know the value of the address. The worst-case scenario is that the element is not in the array, so the computer needs to iterate through the entire array. This operation takes N steps since the maximum number of steps is the size of the array.

- Inserting: Inserting an element is similar to searching. When allocating an array, the computer knows the size of the array. Let's imagine that we want to insert at the end of the array. The computer needs to iterate through the entire array to find the last element and insert the new element. So this operation takes N steps shifting elements plus 1 step to insert the new element.

- Deleting: Deleting an element is similar to inserting. The computer needs to shift elements to fill the gap left by the deleted element. This operation takes N steps shifting elements where N-1 will be the number of elements to shift.

Now that we have seen the basic operations of arrays, let's see how sets perform.

### Sets

Sets contrast with arrays in that they are unordered collections of elements and does not allow duplicates. Sets are implemented using hash tables, which are arrays that store elements in key-value pairs. Sets are used when we need to check if an element is in the set or not.

This constraint causes sets to have a different efficiency for one of the operations. Do you guess which one? Let's see.

When we try to insert a data element into a set, the computer needs to check if the element is already in the set. If the element is not in the set, the computer needs to insert the element. So, for this operation, the coputer first needs to determine that the new data isn't already in the set, and then insert the new data. In few words, the insert operation in a ser requires a previous search so in terms of steps, the insert operation in a set is N steps for the search plus the inserting which worst case scenario is N + 1 step wo 2N + 1 steps in total.

Does it mean that sets are always slower than arrays? Not necessarily. Sets are faster when we need to check if an element is in the set or not. This is because the computer only needs to check the hash table to see if the element is in the set.

> Normally the search operation in an array looks for the first instace of a given value. But sometimes we may want to look for every instance of a given value. For example, say we wanto to count how many times a fiven value appears in an array. How many steps would it take to find all the ocurrences?
> The answer is N steps. The reason is that the computer needs to iterate through the entire array to find all the ocurrences. So, the search operation in an array takes N steps to find all the ocurrences.

The take away from this is that the selection of the right data structure can make a huge difference in the performance of your application, but we cannot obvious the business logic of the application. So, when you are designing your routine, think about the data structures you are going to use and how they will impact the performance of your application. Only uses a set when is needed, for example, when you need to create a list of unique elements. Otherwise, use an array.

We will dive into more data structures in the coming posts. Stay tuned!
